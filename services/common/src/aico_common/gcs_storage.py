"""GCS-backed Storage implementation of the Storage protocol.

Content is stored as GCS objects while metadata (source_hash, validator, content_type,
extraction_path, etc.) is stored in object custom metadata to mirror LocalStorage.
Authentication uses Application Default Credentials. The GCS client is lazily imported and
injectable for offline testing.
"""

from __future__ import annotations

from typing import Any


try:
    from google.api_core.exceptions import NotFound, PreconditionFailed
except ImportError:
    class PreconditionFailed(Exception): pass  # type: ignore
    class NotFound(Exception): pass  # type: ignore


class GcsStorage:
    def __init__(self, bucket_name: str, *, client: Any = None):
        self._bucket_name = bucket_name
        self._client = client

    def _bucket(self):
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client()
        return self._client.bucket(self._bucket_name)

    def _blob(self, key: str):
        return self._bucket().blob(key.lstrip("/"))

    def write(self, key: str, content: str, metadata: dict[str, str] | None = None) -> None:
        blob = self._blob(key)
        if metadata:
            blob.metadata = dict(metadata)
        blob.upload_from_string(content, content_type="text/markdown")

    def read(self, key: str) -> str:
        return self._blob(key).download_as_text()

    def exists(self, key: str) -> bool:
        return self._blob(key).exists()

    def get_metadata(self, key: str) -> dict[str, str]:
        blob = self._blob(key)
        if not blob.exists():
            return {}
        blob.reload()  # fetch object metadata from GCS
        return dict(blob.metadata or {})

    def list_keys(self) -> list[str]:
        return sorted("/" + blob.name for blob in self._bucket().list_blobs())

    def list_entries_with_metadata(self) -> list[tuple[str, dict[str, str]]]:
        return [("/" + blob.name, dict(blob.metadata or {})) for blob in self._bucket().list_blobs()]

    def create_if_absent(self, key: str) -> bool:
        # if_generation_match=0 => "create only if the object does not exist" (atomic).
        # A concurrent create raises PreconditionFailed (412) as a deduplication signal.
        try:
            self._blob(key).upload_from_string(b"", if_generation_match=0)
            return True
        except PreconditionFailed:
            return False

    def delete(self, key: str) -> None:
        try:
            self._blob(key).delete()
        except NotFound:
            pass
