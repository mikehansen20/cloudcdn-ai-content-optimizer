"""Storage tests for LocalStorage implementation."""

import tempfile
import unittest
from pathlib import Path

from aico_common.storage import LocalStorage


class LocalStorageRoundtrip(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalStorage(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_then_read_roundtrip(self):
        self.store.write("/pages/a.md", "# Hello\n")
        self.assertEqual(self.store.read("/pages/a.md"), "# Hello\n")

    def test_exists_reflects_writes(self):
        self.assertFalse(self.store.exists("/pages/a.md"))
        self.store.write("/pages/a.md", "x")
        self.assertTrue(self.store.exists("/pages/a.md"))

    def test_metadata_is_persisted_and_retrievable(self):
        self.store.write("/pages/a.md", "x", metadata={"source_hash": "abc123", "extraction_path": "model"})
        meta = self.store.get_metadata("/pages/a.md")
        self.assertEqual(meta["source_hash"], "abc123")
        self.assertEqual(meta["extraction_path"], "model")

    def test_missing_object_metadata_is_empty(self):
        self.assertEqual(self.store.get_metadata("/nope.md"), {})

    def test_nested_keys_create_directories(self):
        self.store.write("/deep/nested/dir/x.md", "content")
        self.assertTrue(self.store.exists("/deep/nested/dir/x.md"))
        self.assertEqual(self.store.read("/deep/nested/dir/x.md"), "content")

    def test_metadata_file_is_not_mistaken_for_content(self):
        # the .meta sidecar must not shadow content listing/reads
        self.store.write("/a.md", "real", metadata={"k": "v"})
        self.assertEqual(self.store.read("/a.md"), "real")
        self.assertFalse(self.store.exists("/a.md.meta.json"))  # sidecar isn't a first-class object

    def test_list_keys_returns_content_keys_only(self):
        self.store.write("/a.md", "x", metadata={"k": "v"})
        self.store.write("/deep/b.md", "y")
        self.assertEqual(self.store.list_keys(), ["/a.md", "/deep/b.md"])  # no .meta sidecars

    def test_list_keys_empty_when_nothing_written(self):
        self.assertEqual(self.store.list_keys(), [])


if __name__ == "__main__":
    unittest.main()
