"""llms.txt and llms-full.txt builder tests.

llms.txt is a flat list built from object metadata (title, URL, and description). llms-full.txt concatenates stored page bodies.
"""

import tempfile
import unittest

from cascade.llms import (
    build_and_store,
    build_llms_full_txt,
    build_llms_txt,
    main,
    storage_from_env,
)
from aico_common.storage import LocalStorage


def _store_page(store, key, title, url, desc, body="Body text."):
    """Store a page the way the worker does: body content + metadata (no front matter)."""
    store.write(key, f"# {title}\n\n**URL:** {url}\n\n{body}\n",
                metadata={"title": title, "url": url, "description": desc})


class BuildLlmsTxt(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalStorage(self._tmp.name)
        _store_page(self.store, "/a.md", "Prod A", "https://s/a", "Desc A")
        _store_page(self.store, "/b.md", "Art B", "https://s/b", "Desc B")
        _store_page(self.store, "/c.md", "Prod C", "https://s/c", "Desc C")

    def tearDown(self):
        self._tmp.cleanup()

    def test_flat_list_from_metadata(self):
        out = build_llms_txt(self.store, site_title="My Site", site_description="All the things.")
        self.assertIn("# My Site", out)
        self.assertIn("> All the things.", out)
        self.assertIn("- [Prod A](https://s/a): Desc A", out)
        self.assertIn("- [Art B](https://s/b): Desc B", out)
        self.assertIn("- [Prod C](https://s/c): Desc C", out)

    def test_has_no_content_type_sections(self):
        out = build_llms_txt(self.store)
        self.assertNotIn("##", out)  # Flat list without per-type grouping

    def test_entries_sorted_by_url(self):
        out = build_llms_txt(self.store)
        self.assertLess(out.index("https://s/a"), out.index("https://s/b"))
        self.assertLess(out.index("https://s/b"), out.index("https://s/c"))

    def test_description_optional(self):
        _store_page(self.store, "/d.md", "No Desc", "https://s/d", "")
        out = build_llms_txt(self.store)
        self.assertIn("- [No Desc](https://s/d)\n", out + "\n")
        self.assertNotIn("https://s/d):", out)  # no dangling ": " suffix

    def test_excludes_the_index_files_themselves(self):
        self.store.write("/llms.txt", "# stale index")
        self.assertNotIn("stale", build_llms_txt(self.store))


class BuildLlmsFull(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalStorage(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_concatenates_pages_with_separators(self):
        _store_page(self.store, "/a.md", "A", "u", "d", body="AAA")
        _store_page(self.store, "/b.md", "B", "u", "d", body="BBB")
        out = build_llms_full_txt(self.store)
        self.assertIn("AAA", out)
        self.assertIn("BBB", out)
        self.assertIn("---", out)

    def test_respects_the_size_cap(self):
        _store_page(self.store, "/a.md", "A", "u", "d", body="A" * 1000)
        _store_page(self.store, "/b.md", "B", "u", "d", body="B" * 1000)
        # each page chunk ~1KB; a 1200-byte cap fits the first but not both
        out = build_llms_full_txt(self.store, max_bytes=1200)
        self.assertIn("A" * 1000, out)
        self.assertNotIn("B" * 1000, out)


class BuildAndStore(unittest.TestCase):
    def test_writes_both_index_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStorage(tmp)
            _store_page(store, "/a.md", "A", "https://s/a", "d")
            build_and_store(store, site_title="S")
            self.assertTrue(store.exists("/llms.txt"))
            self.assertTrue(store.exists("/llms-full.txt"))
            self.assertIn("- [A](https://s/a): d", store.read("/llms.txt"))


class StorageFromEnv(unittest.TestCase):
    def test_local_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = storage_from_env({"STORAGE": "local", "STORAGE_DIR": tmp})
            self.assertIsInstance(store, LocalStorage)

    def test_gcs_backend_requires_bucket(self):
        with self.assertRaises(ValueError):
            storage_from_env({"STORAGE": "gcs"})


class Main(unittest.TestCase):
    def test_builds_and_stores_via_injected_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStorage(tmp)
            _store_page(store, "/a.md", "A", "https://s/a", "d")
            rc = main(env={"SITE_TITLE": "My Site", "SITE_DESCRIPTION": "Hi."}, storage=store)
            self.assertEqual(rc, 0)
            self.assertTrue(store.exists("/llms.txt"))
            index = store.read("/llms.txt")
            self.assertIn("# My Site", index)
            self.assertIn("> Hi.", index)


if __name__ == "__main__":
    unittest.main()
