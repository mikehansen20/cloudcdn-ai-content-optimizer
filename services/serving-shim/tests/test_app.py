"""Serving-shim tests covering routing and self-heal operations with offline stubs."""

import tempfile
import unittest

from fastapi.testclient import TestClient

from app import (
    app, get_storage, get_settings, get_fetch, get_publisher, Settings, LOOP_GUARD_HEADER,
)
from aico_common.fetch import FetchResult
from aico_common.ssrf import SsrfError
from aico_common.storage import LocalStorage
from aico_common.service_support import path_to_key


class _Publisher:
    def __init__(self):
        self.published = []
        self.flushed = 0
    def publish(self, url):
        self.published.append(url)
    def flush(self):
        self.flushed += 1


def _fetch_returning(result):
    def _fetch(url, *, allowed_hosts=None, extra_headers=None):
        _fetch.seen = {"url": url, "extra_headers": extra_headers or {}}
        return result
    return _fetch


class ShimBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalStorage(self._tmp.name)
        self.pub = _Publisher()
        app.dependency_overrides[get_storage] = lambda: self.store
        app.dependency_overrides[get_publisher] = lambda: self.pub
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self._tmp.cleanup()

    def _settings(self, **over):
        base = dict(storage_backend="local", storage_dir=self._tmp.name, gcs_bucket=None,
                    ai_path_prefix="/_ai_optimized", content_cache_ttl=3600,
                    site_base_url="https://site.test", allowed_hosts=("site.test",),
                    origin_404_behavior="proxy_and_generate", project="p",
                    crawl_topic="ai-optimizer-crawl")
        base.update(over)
        app.dependency_overrides[get_settings] = lambda: Settings(**base)

    def _set_fetch(self, result):
        f = _fetch_returning(result)
        self.f = f
        app.dependency_overrides[get_fetch] = lambda: f


class ServePresent(ShimBase):
    def test_present_object_is_served_with_cache_ttl(self):
        self._settings()
        self._set_fetch(FetchResult(status=200, html="ignored"))
        self.store.write("/blog/post.md", "# Post\n\n**URL:** https://s/blog/post\n\nBody.")
        resp = self.client.get("/_ai_optimized/blog/post")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("# Post", resp.text)
        self.assertEqual(resp.headers["content-type"], "text/markdown; charset=utf-8")
        self.assertEqual(resp.headers["cache-control"], "public, max-age=3600")

    def test_root_maps_to_index(self):
        self._settings()
        self._set_fetch(FetchResult(status=200, html="ignored"))
        self.store.write("/index.md", "# Home")
        resp = self.client.get("/_ai_optimized/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("# Home", resp.text)

    def test_key_mapping_matches_the_worker(self):
        self.assertEqual(path_to_key("/blog/post"), "/blog/post.md")
        self.assertEqual(path_to_key("/"), "/index.md")


class SelfHeal(ShimBase):
    def test_miss_proxies_origin_no_store_and_enqueues_once(self):
        self._settings()
        self._set_fetch(FetchResult(status=200, html="<html>human page</html>"))
        resp = self.client.get("/_ai_optimized/new/page")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("human page", resp.text)
        self.assertEqual(resp.headers["cache-control"], "no-store")  # never cache the fallback
        # proxied the origin URL with the loop-guard header
        self.assertEqual(self.f.seen["url"], "https://site.test/new/page")
        self.assertEqual(self.f.seen["extra_headers"].get(LOOP_GUARD_HEADER), "1")
        # enqueued exactly once + marker created
        self.assertEqual(self.pub.published, ["https://site.test/new/page"])
        self.assertTrue(self.store.exists("/pending/new/page.md"))

    def test_burst_enqueues_once(self):
        self._settings()
        self._set_fetch(FetchResult(status=200, html="<html>x</html>"))
        self.client.get("/_ai_optimized/hot")
        self.client.get("/_ai_optimized/hot")  # marker already present
        self.assertEqual(len(self.pub.published), 1)

    def test_never_302_on_miss(self):
        self._settings()
        self._set_fetch(FetchResult(status=200, html="<html>x</html>"))
        resp = self.client.get("/_ai_optimized/x", follow_redirects=False)
        self.assertNotIn(resp.status_code, (301, 302, 303, 307, 308))

    def test_ssrf_blocked_origin_is_safe_no_publish(self):
        self._settings()
        def _boom():
            def _f(url, *, allowed_hosts=None, extra_headers=None):
                raise SsrfError("origin resolves to a private IP")
            return _f
        app.dependency_overrides[get_fetch] = _boom
        resp = self.client.get("/_ai_optimized/evil")
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.headers["cache-control"], "no-store")
        self.assertEqual(self.pub.published, [])

    def test_notfound_mode_just_404s(self):
        self._settings(origin_404_behavior="notfound")
        self._set_fetch(FetchResult(status=200, html="<html>x</html>"))
        resp = self.client.get("/_ai_optimized/missing")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.pub.published, [])


class ServeLlms(ShimBase):
    """Static index files (llms.txt and llms-full.txt) served directly as plain text."""

    def test_llms_txt_served_from_its_own_key_as_plain_text(self):
        self._settings()
        self._set_fetch(FetchResult(status=200, html="ignored"))
        self.store.write("/llms.txt", "# Site\n\n- [Home](https://s/): desc\n")
        resp = self.client.get("/llms.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("- [Home]", resp.text)
        self.assertTrue(resp.headers["content-type"].startswith("text/plain"))
        self.assertEqual(resp.headers["cache-control"], "public, max-age=3600")

    def test_llms_full_txt_served(self):
        self._settings()
        self._set_fetch(FetchResult(status=200, html="ignored"))
        self.store.write("/llms-full.txt", "# Page\n\nBody\n")
        resp = self.client.get("/llms-full.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Body", resp.text)
        self.assertTrue(resp.headers["content-type"].startswith("text/plain"))

    def test_llms_also_served_when_ua_rewritten_through_prefix(self):
        # AI-crawler UA path: the edge plugin rewrites /llms.txt -> /_ai_optimized/llms.txt
        self._settings()
        self._set_fetch(FetchResult(status=200, html="ignored"))
        self.store.write("/llms.txt", "# Site\n")
        resp = self.client.get("/_ai_optimized/llms.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("# Site", resp.text)

    def test_missing_llms_404s_without_selfheal_or_enqueue(self):
        self._settings()
        self._set_fetch(FetchResult(status=200, html="<html>origin 404 page</html>"))
        resp = self.client.get("/llms.txt")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.pub.published, [])         # never enqueue an index file
        self.assertFalse(self.store.exists("/pending/llms.txt"))


class Healthz(ShimBase):
    def test_healthz(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)


if __name__ == "__main__":
    unittest.main()
