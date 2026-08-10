"""Worker service tests covering pipeline orchestration using offline stubs."""

import tempfile
import unittest

from fastapi.testclient import TestClient

from aico_common.fetch import FetchResult, Validator
from aico_common.ssrf import SsrfError
from app import app, get_fetch, get_model_client, get_renderer, get_storage
from cascade.model import StubModelClient
from aico_common.storage import LocalStorage

GENERIC_HTML = "<html><body><h1>Welcome</h1><p>Some marketing prose here.</p></body></html>"


def _fetch_returning(result, *, seen=None):
    def _fetch(url, *, validator=None, allowed_hosts=None, user_agent=None):
        if seen is not None:
            seen["user_agent"] = user_agent
        return result
    return _fetch


class WorkerService(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalStorage(self._tmp.name)
        app.dependency_overrides[get_storage] = lambda: self.store
        app.dependency_overrides[get_model_client] = lambda: StubModelClient()
        app.dependency_overrides[get_renderer] = lambda: None
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self._tmp.cleanup()

    def _set_fetch(self, result):
        app.dependency_overrides[get_fetch] = lambda: _fetch_returning(result)

    def test_healthz(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_new_url_is_generated_and_stored(self):
        self._set_fetch(FetchResult(status=200, html=GENERIC_HTML,
                                    validator=Validator(etag='"e1"'), body_hash="H1"))
        resp = self.client.post("/process", json={"url": "https://site.test/page"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["outcome"], "generated")
        self.assertEqual(body["key"], "/page.md")
        self.assertEqual(body["extraction_path"], "model")  # generic -> escalate -> (stub) model
        # persisted
        self.assertTrue(self.store.exists("/page.md"))
        self.assertIn("Welcome", self.store.read("/page.md"))
        # object metadata is the off-document provenance record (full contract)
        md = self.store.get_metadata("/page.md")
        self.assertEqual(md["source_hash"], "H1")
        self.assertEqual(md["url"], "https://site.test/page")
        self.assertEqual(md["content_type"], "generic")
        self.assertEqual(md["extraction_path"], "model")
        self.assertTrue(md["title"])
        self.assertTrue(md["model"])          # model path records the model id
        self.assertTrue(md["generated_at"])
        self.assertEqual(md["etag"], '"e1"')

    def test_clears_the_self_heal_marker_after_writing(self):
        # the serving-shim creates pending/<key>; the worker must delete it on write
        self.store.create_if_absent("/pending/page.md")
        self._set_fetch(FetchResult(status=200, html=GENERIC_HTML,
                                    validator=Validator(etag='"e1"'), body_hash="H1"))
        self.client.post("/process", json={"url": "https://site.test/page"})
        self.assertTrue(self.store.exists("/page.md"))
        self.assertFalse(self.store.exists("/pending/page.md"))  # marker cleared

    def test_forwards_the_distinctive_crawler_user_agent(self):
        seen = {}
        app.dependency_overrides[get_fetch] = lambda: _fetch_returning(
            FetchResult(status=200, html=GENERIC_HTML, body_hash="H1"), seen=seen)
        self.client.post("/process", json={"url": "https://site.test/page"})
        self.assertIn("AIContentOptimizer", seen["user_agent"])  # allowlistable, not a browser
        self.assertNotIn("Mozilla", seen["user_agent"])

    def test_unchanged_hash_is_skipped_without_calling_the_model(self):
        # pre-store the same content hash
        self.store.write("/page.md", "old markdown", metadata={"source_hash": "H1"})

        class SpyModel:
            model_id = "spy"
            called = False
            def extract(self, **kwargs):
                SpyModel.called = True
                raise AssertionError("model must not be called on unchanged content")

        app.dependency_overrides[get_model_client] = lambda: SpyModel()
        self._set_fetch(FetchResult(status=200, html=GENERIC_HTML, body_hash="H1"))
        resp = self.client.post("/process", json={"url": "https://site.test/page"})
        self.assertEqual(resp.json()["outcome"], "unchanged")
        self.assertFalse(SpyModel.called)
        self.assertEqual(self.store.read("/page.md"), "old markdown")  # not overwritten

    def test_304_is_unchanged(self):
        self._set_fetch(FetchResult(status=304))
        resp = self.client.post("/process", json={"url": "https://site.test/page"})
        self.assertEqual(resp.json()["outcome"], "unchanged-304")

    def test_fetch_error_is_502(self):
        self._set_fetch(FetchResult(status=403))
        resp = self.client.post("/process", json={"url": "https://site.test/page"})
        self.assertEqual(resp.status_code, 502)

    def test_ssrf_blocked_is_400(self):
        def _boom():
            def _fetch(url, *, validator=None, allowed_hosts=None, user_agent=None):
                raise SsrfError("host resolves to non-public IP")
            return _fetch
        app.dependency_overrides[get_fetch] = _boom
        resp = self.client.post("/process", json={"url": "https://private.test/x"})
        self.assertEqual(resp.status_code, 400)


class PubSubPush(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalStorage(self._tmp.name)
        app.dependency_overrides[get_storage] = lambda: self.store
        app.dependency_overrides[get_model_client] = lambda: StubModelClient()
        app.dependency_overrides[get_renderer] = lambda: None
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self._tmp.cleanup()

    def _envelope(self, data_bytes):
        import base64
        return {"message": {"data": base64.b64encode(data_bytes).decode()},
                "subscription": "projects/p/subscriptions/s"}

    def test_push_envelope_processes_the_url(self):
        app.dependency_overrides[get_fetch] = lambda: _fetch_returning(
            FetchResult(status=200, html=GENERIC_HTML, body_hash="H1"))
        env = self._envelope(b'{"url": "https://site.test/page"}')
        resp = self.client.post("/pubsub", json=env)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.store.exists("/page.md"))

    def test_malformed_message_is_acked_not_retried(self):
        env = self._envelope(b"this is not json")
        resp = self.client.post("/pubsub", json=env)
        self.assertEqual(resp.status_code, 200)  # 2xx = ack; retrying can't fix it
        self.assertEqual(resp.json()["status"], "bad-message")

    def test_message_without_url_is_acked(self):
        env = self._envelope(b'{"not_url": "x"}')
        resp = self.client.post("/pubsub", json=env)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "bad-message")


class StorageSelection(unittest.TestCase):
    def test_gcs_backend_selects_gcs_storage(self):
        from app import Settings, get_storage
        from aico_common.gcs_storage import GcsStorage

        settings = Settings(storage_backend="gcs", storage_dir="/x", gcs_bucket="b",
                            allowed_hosts=None, renderer_url=None, renderer_auth=False, model="stub",
                            project="p", location="l", model_id="m")
        self.assertIsInstance(get_storage(settings), GcsStorage)

    def test_gcs_backend_without_bucket_errors(self):
        from app import Settings, get_storage

        settings = Settings(storage_backend="gcs", storage_dir="/x", gcs_bucket=None,
                            allowed_hosts=None, renderer_url=None, renderer_auth=False, model="stub",
                            project="p", location="l", model_id="m")
        with self.assertRaises(RuntimeError):
            get_storage(settings)


if __name__ == "__main__":
    unittest.main()
