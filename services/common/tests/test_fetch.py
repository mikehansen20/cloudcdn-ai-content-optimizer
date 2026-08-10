"""Fetcher tests covering conditional GET, browser User-Agent, and SSRF protection.

Both DNS resolution and the HTTP transport are injected so tests execute offline and deterministically.
"""

import unittest

from aico_common.fetch import Response, Validator, fetch
from aico_common.ssrf import SsrfError


def _public(_host):
    return ["93.184.216.34"]


def _private(_host):
    return ["10.0.0.5"]


class _Transport:
    """Records what fetch() sent and returns a canned Response."""

    def __init__(self, response):
        self.response = response
        self.called = False
        self.url = None
        self.headers = None

    def __call__(self, url, headers):
        self.called = True
        self.url = url
        self.headers = dict(headers)
        return self.response


class Ok200(unittest.TestCase):
    def test_returns_html_body_hash_and_validator(self):
        t = _Transport(Response(200, {"ETag": '"abc"', "Last-Modified": "Wed, 01 Jul 2026 00:00:00 GMT"},
                                b"<html>hi</html>"))
        r = fetch("https://example.test/p", allowed_hosts=["example.test"], resolve=_public, transport=t)
        self.assertTrue(r.ok)
        self.assertEqual(r.html, "<html>hi</html>")
        self.assertEqual(len(r.body_hash), 64)  # sha256 hex
        self.assertEqual(r.validator.etag, '"abc"')
        self.assertEqual(r.validator.last_modified, "Wed, 01 Jul 2026 00:00:00 GMT")

    def test_reads_response_headers_case_insensitively(self):
        t = _Transport(Response(200, {"etag": '"xyz"'}, b"x"))
        r = fetch("https://example.test/p", allowed_hosts=["example.test"], resolve=_public, transport=t)
        self.assertEqual(r.validator.etag, '"xyz"')

    def test_sends_the_distinctive_crawler_user_agent(self):
        # A distinctive, allowlistable User-Agent rather than a browser masquerade.
        t = _Transport(Response(200, {}, b"x"))
        fetch("https://example.test/p", allowed_hosts=["example.test"], resolve=_public, transport=t)
        ua = t.headers.get("User-Agent", "")
        self.assertIn("AIContentOptimizer", ua)
        self.assertNotIn("Mozilla", ua)

    def test_user_agent_is_overridable(self):
        t = _Transport(Response(200, {}, b"x"))
        fetch("https://example.test/p", allowed_hosts=["example.test"], resolve=_public,
              transport=t, user_agent="Custom/9.9")
        self.assertEqual(t.headers.get("User-Agent"), "Custom/9.9")

    def test_extra_headers_are_sent(self):
        # The serving shim proxies the origin with a loop-guard header so the edge plugin ignores the fetch.
        t = _Transport(Response(200, {}, b"x"))
        fetch("https://example.test/p", allowed_hosts=["example.test"], resolve=_public,
              transport=t, extra_headers={"X-From-LLM-Optimizer": "1"})
        self.assertEqual(t.headers.get("X-From-LLM-Optimizer"), "1")


class Conditional(unittest.TestCase):
    def test_sends_conditional_headers_from_a_validator(self):
        t = _Transport(Response(304, {}, b""))
        v = Validator(etag='"abc"', last_modified="Wed, 01 Jul 2026 00:00:00 GMT")
        fetch("https://example.test/p", validator=v, allowed_hosts=["example.test"],
              resolve=_public, transport=t)
        self.assertEqual(t.headers.get("If-None-Match"), '"abc"')
        self.assertEqual(t.headers.get("If-Modified-Since"), "Wed, 01 Jul 2026 00:00:00 GMT")

    def test_304_is_unchanged_with_no_html(self):
        t = _Transport(Response(304, {}, b""))
        r = fetch("https://example.test/p", allowed_hosts=["example.test"], resolve=_public, transport=t)
        self.assertTrue(r.unchanged)
        self.assertIsNone(r.html)
        self.assertFalse(r.ok)


class SsrfGuarded(unittest.TestCase):
    def test_private_ip_raises_before_any_fetch(self):
        t = _Transport(Response(200, {}, b"x"))
        with self.assertRaises(SsrfError):
            fetch("https://example.test/p", allowed_hosts=["example.test"], resolve=_private, transport=t)
        self.assertFalse(t.called)  # guard runs before the transport


class NonOk(unittest.TestCase):
    def test_403_returns_status_without_html(self):
        t = _Transport(Response(403, {}, b"blocked"))
        r = fetch("https://example.test/p", allowed_hosts=["example.test"], resolve=_public, transport=t)
        self.assertEqual(r.status, 403)
        self.assertIsNone(r.html)
        self.assertFalse(r.ok)


if __name__ == "__main__":
    unittest.main()
