"""llms.txt and llms-full.txt builders.

`llms.txt` builds a flat index containing an H1 title, optional blockquote summary,
and URL entries sorted by URL, sourced from object metadata.
`llms-full.txt` concatenates page bodies separated by delimiters up to a configured size limit.
"""

from __future__ import annotations

import json
import os
from typing import Mapping

from aico_common.storage import LocalStorage, Storage

from concurrent.futures import ThreadPoolExecutor

LLMS_KEY = "/llms.txt"
LLMS_FULL_KEY = "/llms-full.txt"
_INDEX_KEYS = {LLMS_KEY, LLMS_FULL_KEY}
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_CONCURRENCY = 32


def _page_keys(storage: Storage) -> list[str]:
    return [k for k in storage.list_keys() if k not in _INDEX_KEYS]


def build_llms_txt(storage: Storage, *, site_title: str = "Site",
                   site_description: str | None = None,
                   max_workers: int = DEFAULT_CONCURRENCY) -> str:
    lines = [f"# {site_title}", ""]
    if site_description:
        lines += [f"> {site_description}", ""]

    if hasattr(storage, "list_entries_with_metadata"):
        page_entries = [(k, md) for k, md in storage.list_entries_with_metadata() if k not in _INDEX_KEYS]
    else:
        keys = _page_keys(storage)
        workers = min(max_workers, max(1, len(keys)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            metadata_list = list(executor.map(storage.get_metadata, keys))
        page_entries = list(zip(keys, metadata_list))

    entries: list[tuple[str, str]] = []
    for key, md in page_entries:
        if not md:
            continue
        url = md.get("url")
        if not url:
            continue  # no metadata -> can't index it
        entry = f"- [{md.get('title', 'Untitled')}]({url})"
        if md.get("description"):
            entry += f": {md['description']}"
        entries.append((url, entry))

    lines += [entry for _, entry in sorted(entries)]
    return "\n".join(lines).rstrip() + "\n"


def build_llms_full_txt(storage: Storage, *, max_bytes: int = DEFAULT_MAX_BYTES,
                        max_workers: int = DEFAULT_CONCURRENCY) -> str:
    keys = sorted(_page_keys(storage))
    workers = min(max_workers, max(1, len(keys)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        bodies = list(executor.map(storage.read, keys))

    parts: list[str] = []
    total = 0
    for chunk_raw in bodies:
        chunk = chunk_raw.rstrip() + "\n\n---\n\n"
        size = len(chunk.encode("utf-8"))
        if total + size > max_bytes:
            break  # Size cap reached, stop concatenation.
        parts.append(chunk)
        total += size
    return "".join(parts).rstrip() + "\n"


def build_and_store(storage: Storage, *, site_title: str = "Site",
                    site_description: str | None = None,
                    max_bytes: int = DEFAULT_MAX_BYTES) -> None:
    storage.write(LLMS_KEY, build_llms_txt(storage, site_title=site_title,
                                           site_description=site_description))
    storage.write(LLMS_FULL_KEY, build_llms_full_txt(storage, max_bytes=max_bytes))


# --- Cloud Run job entrypoint (Scheduler-triggered) ---

def storage_from_env(env: Mapping[str, str]) -> Storage:
    """Select the storage backend from env (mirrors the worker's selection)."""
    if env.get("STORAGE", "local") == "gcs":
        bucket = env.get("GCS_BUCKET")
        if not bucket:
            raise ValueError("STORAGE=gcs requires GCS_BUCKET")
        from aico_common.gcs_storage import GcsStorage

        return GcsStorage(bucket)
    return LocalStorage(env.get("STORAGE_DIR", "/tmp/aico-output"))


def main(argv=None, *, env: Mapping[str, str] | None = None,
         storage: Storage | None = None) -> int:
    """Rebuild llms.txt / llms-full.txt from the stored pages (batch job)."""
    env = env if env is not None else os.environ
    if storage is None:
        storage = storage_from_env(env)
    build_and_store(storage, site_title=env.get("SITE_TITLE", "Site"),
                    site_description=env.get("SITE_DESCRIPTION") or None)
    print(json.dumps({"stage": "llms", "outcome": "built"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
