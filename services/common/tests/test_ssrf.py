"""SSRF fetch-guard tests covering host allowlisting and private IP rejection.

DNS resolution is injected so tests are deterministic and offline.
"""

import unittest

from aico_common.ssrf import SsrfError, assert_safe_url


def _resolver(mapping):
    """Return a fake resolver: host -> list of IPs."""
    return lambda host: mapping[host]


PUBLIC = _resolver({"example.test": ["93.184.216.34"]})


class Scheme(unittest.TestCase):
    def test_rejects_non_http_schemes(self):
        for url in ("file:///etc/passwd", "ftp://example.test/x", "gopher://example.test"):
            with self.assertRaises(SsrfError):
                assert_safe_url(url, allowed_hosts=["example.test"], resolve=PUBLIC)

    def test_rejects_missing_host(self):
        with self.assertRaises(SsrfError):
            assert_safe_url("http:///nohost", resolve=PUBLIC)


class AllowedHosts(unittest.TestCase):
    def test_allows_listed_host_resolving_public(self):
        assert_safe_url("https://example.test/page", allowed_hosts=["example.test"], resolve=PUBLIC)

    def test_rejects_host_not_in_allow_list(self):
        with self.assertRaises(SsrfError):
            assert_safe_url("https://evil.test/x", allowed_hosts=["example.test"],
                            resolve=_resolver({"evil.test": ["93.184.216.34"]}))

    def test_host_match_is_case_insensitive(self):
        assert_safe_url("https://Example.TEST/x", allowed_hosts=["example.test"], resolve=PUBLIC)


class PrivateAndMetadataIps(unittest.TestCase):
    def test_rejects_cloud_metadata_ip_literal(self):
        with self.assertRaises(SsrfError):
            assert_safe_url("http://169.254.169.254/latest/meta-data/",
                            resolve=_resolver({"169.254.169.254": ["169.254.169.254"]}))

    def test_rejects_rfc1918_private(self):
        with self.assertRaises(SsrfError):
            assert_safe_url("http://private.test/x", allowed_hosts=["private.test"],
                            resolve=_resolver({"private.test": ["10.0.0.5"]}))

    def test_rejects_loopback(self):
        with self.assertRaises(SsrfError):
            assert_safe_url("http://localhost/x", allowed_hosts=["localhost"],
                            resolve=_resolver({"localhost": ["127.0.0.1"]}))

    def test_rejects_when_any_resolved_ip_is_private(self):
        # DNS-rebinding style: one public + one private -> reject
        mixed = _resolver({"example.test": ["93.184.216.34", "10.1.2.3"]})
        with self.assertRaises(SsrfError):
            assert_safe_url("https://example.test/x", allowed_hosts=["example.test"], resolve=mixed)


class NoAllowList(unittest.TestCase):
    def test_allows_any_public_host_when_no_allow_list(self):
        # the serving shim may guard only by IP class when no fixed host is configured
        assert_safe_url("https://example.test/x", resolve=PUBLIC)


if __name__ == "__main__":
    unittest.main()
