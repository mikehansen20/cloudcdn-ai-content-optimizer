"""GcsStorage tests covering the GCS implementation of the Storage protocol using an offline fake client."""

import unittest

from aico_common.gcs_storage import GcsStorage, NotFound, PreconditionFailed
from aico_common.storage import Storage


# --- minimal in-memory fake of the google-cloud-storage client surface ---
class _FakeBlob:
    def __init__(self, store, key):
        self._store = store
        self._key = key
        self.name = key
        self.metadata = None

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        if if_generation_match == 0 and self._key in self._store:
            raise PreconditionFailed("object already exists")
        self._store[self._key] = {"data": data, "meta": dict(self.metadata or {})}

    def download_as_text(self):
        return self._store[self._key]["data"]

    def exists(self):
        return self._key in self._store

    def delete(self):
        if self._key not in self._store:
            raise NotFound("no such object")
        del self._store[self._key]

    def reload(self):
        self.metadata = self._store.get(self._key, {}).get("meta", {})


class _FakeBucket:
    def __init__(self, store):
        self._store = store

    def blob(self, key):
        return _FakeBlob(self._store, key)

    def list_blobs(self):
        return [_FakeBlob(self._store, key) for key in self._store]


class _FakeClient:
    def __init__(self):
        self.objects = {}

    def bucket(self, name):
        return _FakeBucket(self.objects)


class GcsStorageRoundtrip(unittest.TestCase):
    def setUp(self):
        self.client = _FakeClient()
        self.store = GcsStorage("my-bucket", client=self.client)

    def test_implements_storage_protocol(self):
        self.assertIsInstance(self.store, Storage)

    def test_write_then_read_roundtrip(self):
        self.store.write("/pages/a.md", "# Hello\n")
        self.assertEqual(self.store.read("/pages/a.md"), "# Hello\n")

    def test_key_leading_slash_is_stripped_for_the_object_name(self):
        self.store.write("/pages/a.md", "x")
        self.assertIn("pages/a.md", self.client.objects)  # no leading slash in the object key

    def test_exists_reflects_writes(self):
        self.assertFalse(self.store.exists("/pages/a.md"))
        self.store.write("/pages/a.md", "x")
        self.assertTrue(self.store.exists("/pages/a.md"))

    def test_metadata_is_stored_as_object_metadata(self):
        self.store.write("/pages/a.md", "x", metadata={"source_hash": "abc", "content_type": "product"})
        meta = self.store.get_metadata("/pages/a.md")
        self.assertEqual(meta["source_hash"], "abc")
        self.assertEqual(meta["content_type"], "product")

    def test_missing_object_metadata_is_empty(self):
        self.assertEqual(self.store.get_metadata("/nope.md"), {})

    def test_list_keys_returns_object_keys_with_leading_slash(self):
        self.store.write("/a.md", "x")
        self.store.write("/pages/b.md", "y")
        self.assertEqual(self.store.list_keys(), ["/a.md", "/pages/b.md"])

    def test_create_if_absent_is_atomic(self):
        self.assertTrue(self.store.create_if_absent("/pending/a.md"))   # created
        self.assertFalse(self.store.create_if_absent("/pending/a.md"))  # 412 -> already exists
        self.assertTrue(self.store.exists("/pending/a.md"))

    def test_delete_removes_and_tolerates_missing(self):
        self.store.write("/pending/a.md", "")
        self.store.delete("/pending/a.md")
        self.assertFalse(self.store.exists("/pending/a.md"))
        self.store.delete("/pending/a.md")  # NotFound swallowed without error


if __name__ == "__main__":
    unittest.main()
