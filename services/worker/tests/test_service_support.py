"""Worker service support helper tests covering URL key mapping, correlation IDs, and structured logging."""

import io
import json
import unittest
from contextlib import redirect_stdout

from aico_common.service_support import log_event, new_correlation_id, url_to_key


class UrlToKey(unittest.TestCase):
    def test_path_becomes_markdown_key(self):
        self.assertEqual(url_to_key("https://site.test/foo/bar"), "/foo/bar.md")

    def test_root_maps_to_index(self):
        self.assertEqual(url_to_key("https://site.test/"), "/index.md")

    def test_empty_path_maps_to_index(self):
        self.assertEqual(url_to_key("https://site.test"), "/index.md")

    def test_trailing_slash_becomes_index(self):
        self.assertEqual(url_to_key("https://site.test/foo/"), "/foo/index.md")

    def test_ignores_query_and_fragment(self):
        self.assertEqual(url_to_key("https://site.test/foo?q=1#x"), "/foo.md")


class CorrelationId(unittest.TestCase):
    def test_is_short_hex_and_unique(self):
        a, b = new_correlation_id(), new_correlation_id()
        self.assertEqual(len(a), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in a))
        self.assertNotEqual(a, b)


class LogEvent(unittest.TestCase):
    def test_emits_one_json_line_with_fields(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            log_event("cid123", "fetch", url="https://site.test/x", outcome="200", nothing=None)
        line = buf.getvalue().strip()
        record = json.loads(line)
        self.assertEqual(record["correlation_id"], "cid123")
        self.assertEqual(record["stage"], "fetch")
        self.assertEqual(record["outcome"], "200")
        self.assertNotIn("nothing", record)  # None-valued fields are dropped


if __name__ == "__main__":
    unittest.main()
