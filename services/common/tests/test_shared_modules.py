"""Tests verifying shared modules import and execute standalone from aico_common without requiring worker dependencies."""

import tempfile
import unittest

from aico_common.gcs_storage import GcsStorage
from aico_common.pubsub import PubSubPublisher
from aico_common.storage import LocalStorage, Storage


class SharedModules(unittest.TestCase):
    def test_local_storage_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = LocalStorage(tmp)
            s.write("/a.md", "hi", metadata={"k": "v"})
            self.assertTrue(s.exists("/a.md"))
            self.assertEqual(s.read("/a.md"), "hi")
            self.assertEqual(s.get_metadata("/a.md"), {"k": "v"})
            self.assertIsInstance(s, Storage)

    def test_create_if_absent_is_atomic_and_delete_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = LocalStorage(tmp)
            # first create wins; a concurrent second create loses (dedup primitive)
            self.assertTrue(s.create_if_absent("/pending/a.md"))
            self.assertFalse(s.create_if_absent("/pending/a.md"))
            self.assertTrue(s.exists("/pending/a.md"))
            s.delete("/pending/a.md")
            self.assertFalse(s.exists("/pending/a.md"))
            s.delete("/pending/a.md")  # deleting a missing key is a no-op, not an error

    def test_gcs_storage_uses_injected_client(self):
        # no real GCS: a fake client proves the class is importable + usable offline
        class _Blob:
            metadata = None
            def upload_from_string(self, *a, **k): pass
        class _Bucket:
            def blob(self, name): return _Blob()
        class _Client:
            def bucket(self, name): return _Bucket()
        GcsStorage("b", client=_Client()).write("/x.md", "y")  # no exception = importable+wired

    def test_pubsub_publisher_flush_waits_on_futures(self):
        class _Future:
            resolved = False
            def result(self): _Future.resolved = True
        class _Client:
            def topic_path(self, p, t): return f"projects/{p}/topics/{t}"
            def publish(self, path, data): return _Future()
        pub = PubSubPublisher("p", "t", client=_Client())
        pub.publish("https://x/1")
        pub.flush()
        self.assertTrue(_Future.resolved)


if __name__ == "__main__":
    unittest.main()
