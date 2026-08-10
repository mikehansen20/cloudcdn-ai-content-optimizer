"""Output storage seam protocol and implementations.

Shared by the worker, enumerator, index building jobs, and serving-shim.
Content is keyed by path, with metadata stored separately. Includes a local filesystem
implementation for offline testing alongside the GCS implementation behind the Storage protocol.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Storage(Protocol):
    def write(self, key: str, content: str, metadata: dict[str, str] | None = None) -> None: ...
    def read(self, key: str) -> str: ...
    def exists(self, key: str) -> bool: ...
    def get_metadata(self, key: str) -> dict[str, str]: ...
    def list_keys(self) -> list[str]: ...
    # Atomic create-if-absent primitive for pending markers.
    # Returns True iff THIS call created the object; False if it already existed.
    def create_if_absent(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Filesystem-backed storage. Content under ``base``; metadata in ``base/.meta``
    so metadata sidecars never collide with the content key namespace."""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)

    def _content_path(self, key: str) -> Path:
        return self.base / key.lstrip("/")

    def _meta_path(self, key: str) -> Path:
        return self.base / ".meta" / (key.lstrip("/") + ".json")

    def write(self, key: str, content: str, metadata: dict[str, str] | None = None) -> None:
        content_path = self._content_path(key)
        content_path.parent.mkdir(parents=True, exist_ok=True)
        content_path.write_text(content, encoding="utf-8")

        meta_path = self._meta_path(key)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(metadata or {}, ensure_ascii=False), encoding="utf-8")

    def read(self, key: str) -> str:
        return self._content_path(key).read_text(encoding="utf-8")

    def exists(self, key: str) -> bool:
        return self._content_path(key).is_file()

    def get_metadata(self, key: str) -> dict[str, str]:
        meta_path = self._meta_path(key)
        if not meta_path.is_file():
            return {}
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def list_keys(self) -> list[str]:
        if not self.base.exists():
            return []
        return sorted(
            "/" + str(p.relative_to(self.base))
            for p in self.base.rglob("*")
            if p.is_file() and ".meta" not in p.relative_to(self.base).parts
        )

    def create_if_absent(self, key: str) -> bool:
        path = self._content_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.open("x").close()  # O_EXCL: atomic exclusive create
            return True
        except FileExistsError:
            return False

    def delete(self, key: str) -> None:
        self._content_path(key).unlink(missing_ok=True)
        self._meta_path(key).unlink(missing_ok=True)
