"""Enumerator tests covering sitemap parsing, glob filtering, index recursion, and URL publishing."""

import unittest

from cascade.enumerator import (
    PubSubPublisher,
    config_from_env,
    enumerate_urls,
    main,
    matches_globs,
    parse_sitemap,
    run_enumerator,
)


class _Result:
    def __init__(self, html, ok=True):
        self.html = html
        self.ok = ok
        self.status = 200 if ok else 500


URLSET = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://site.test/a</loc></url>
  <url><loc>https://site.test/b</loc></url>
</urlset>"""

INDEX = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://site.test/sitemap-1.xml</loc></sitemap>
</sitemapindex>"""


class ParseSitemap(unittest.TestCase):
    def test_urlset_returns_page_locs(self):
        pages, subs = parse_sitemap(URLSET)
        self.assertEqual(pages, ["https://site.test/a", "https://site.test/b"])
        self.assertEqual(subs, [])

    def test_sitemapindex_returns_sub_sitemaps(self):
        pages, subs = parse_sitemap(INDEX)
        self.assertEqual(pages, [])
        self.assertEqual(subs, ["https://site.test/sitemap-1.xml"])


class Globs(unittest.TestCase):
    def test_include_filters(self):
        self.assertTrue(matches_globs("https://s/x/y", ["/x/*"], None))
        self.assertFalse(matches_globs("https://s/z", ["/x/*"], None))

    def test_exclude_wins_over_include(self):
        self.assertFalse(matches_globs("https://s/cart/1", ["/*"], ["/cart/*"]))

    def test_default_allows_all(self):
        self.assertTrue(matches_globs("https://s/anything", None, None))


class Enumerate(unittest.TestCase):
    def test_recurses_index_into_pages(self):
        results = {
            "https://site.test/sitemap.xml": _Result(INDEX),
            "https://site.test/sitemap-1.xml": _Result(URLSET),
        }
        fetch = lambda url, allowed_hosts=None: results[url]
        urls = list(enumerate_urls("https://site.test/sitemap.xml", fetch=fetch))
        self.assertEqual(urls, ["https://site.test/a", "https://site.test/b"])

    def test_applies_globs(self):
        fetch = lambda url, allowed_hosts=None: _Result(URLSET)
        urls = list(enumerate_urls("https://site.test/sitemap.xml", fetch=fetch, include=["/a"]))
        self.assertEqual(urls, ["https://site.test/a"])

    def test_unfetchable_sitemap_yields_nothing(self):
        fetch = lambda url, allowed_hosts=None: _Result("", ok=False)
        self.assertEqual(list(enumerate_urls("https://site.test/sitemap.xml", fetch=fetch)), [])


class RunEnumerator(unittest.TestCase):
    def test_publishes_each_url_and_counts(self):
        fetch = lambda url, allowed_hosts=None: _Result(URLSET)
        published = []

        class _Pub:
            def publish(self, url):
                published.append(url)

        count = run_enumerator("https://site.test/sitemap.xml", _Pub(), fetch=fetch)
        self.assertEqual(count, 2)
        self.assertEqual(published, ["https://site.test/a", "https://site.test/b"])


class _FakeFuture:
    def __init__(self):
        self.resolved = False

    def result(self, timeout=None):
        self.resolved = True
        return "msg-id"


class _FakePubSubClient:
    def __init__(self):
        self.published = []
        self.futures = []

    def topic_path(self, project, topic):
        return f"projects/{project}/topics/{topic}"

    def publish(self, topic_path, data):
        fut = _FakeFuture()
        self.published.append((topic_path, data))
        self.futures.append(fut)
        return fut


class PubSubPublisherFlush(unittest.TestCase):
    def test_flush_waits_for_every_publish_future(self):
        # A batching publisher returns futures; if the job exits without
        # resolving them, messages are silently dropped. flush() must block.
        client = _FakePubSubClient()
        pub = PubSubPublisher("proj", "my-topic", client=client)
        pub.publish("https://s/a")
        pub.publish("https://s/b")
        self.assertTrue(all(not f.resolved for f in client.futures))  # not yet
        pub.flush()
        self.assertEqual(len(client.published), 2)
        self.assertTrue(all(f.resolved for f in client.futures))  # all confirmed

    def test_main_flushes_the_publisher(self):
        fetch = lambda url, allowed_hosts=None: _Result(URLSET)

        class _SpyPub:
            def __init__(self):
                self.published = []
                self.flushed = False

            def publish(self, url):
                self.published.append(url)

            def flush(self):
                self.flushed = True

        spy = _SpyPub()
        main(env={"SITE_BASE_URL": "https://site.test"}, fetch=fetch, publisher=spy)
        self.assertEqual(len(spy.published), 2)
        self.assertTrue(spy.flushed)


class ConfigFromEnv(unittest.TestCase):
    def test_explicit_sitemap_url_wins(self):
        cfg = config_from_env({"SITEMAP_URL": "https://s.test/custom.xml",
                               "SITE_BASE_URL": "https://s.test"})
        self.assertEqual(cfg.sitemap_url, "https://s.test/custom.xml")

    def test_sitemap_defaults_from_site_base_url(self):
        cfg = config_from_env({"SITE_BASE_URL": "https://s.test/"})
        self.assertEqual(cfg.sitemap_url, "https://s.test/sitemap.xml")

    def test_project_and_topic(self):
        cfg = config_from_env({"SITE_BASE_URL": "https://s.test",
                               "GCP_PROJECT": "proj-x", "CRAWL_TOPIC": "my-topic"})
        self.assertEqual(cfg.project, "proj-x")
        self.assertEqual(cfg.topic, "my-topic")

    def test_include_exclude_parsed_as_lists(self):
        cfg = config_from_env({"SITE_BASE_URL": "https://s.test",
                               "INCLUDE_PATHS": "/a/*, /b/*", "EXCLUDE_PATHS": "/cart/*"})
        self.assertEqual(cfg.include, ["/a/*", "/b/*"])
        self.assertEqual(cfg.exclude, ["/cart/*"])

    def test_site_hosts_becomes_allowed_hosts_tuple(self):
        cfg = config_from_env({"SITE_BASE_URL": "https://s.test", "SITE_HOSTS": "s.test, www.s.test"})
        self.assertEqual(cfg.allowed_hosts, ("s.test", "www.s.test"))

    def test_no_site_hosts_means_none(self):
        cfg = config_from_env({"SITE_BASE_URL": "https://s.test"})
        self.assertIsNone(cfg.allowed_hosts)

    def test_missing_sitemap_and_base_url_raises(self):
        with self.assertRaises(ValueError):
            config_from_env({})


class Main(unittest.TestCase):
    def test_enumerates_and_publishes_via_injected_deps(self):
        env = {"SITE_BASE_URL": "https://site.test", "INCLUDE_PATHS": "/a"}
        fetch = lambda url, allowed_hosts=None: _Result(URLSET)
        published = []

        class _Pub:
            def publish(self, url):
                published.append(url)

        rc = main(env=env, fetch=fetch, publisher=_Pub())
        self.assertEqual(rc, 0)
        self.assertEqual(published, ["https://site.test/a"])


if __name__ == "__main__":
    unittest.main()
