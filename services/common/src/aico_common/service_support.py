"""Shared service helpers: path/URL to storage key mapping, correlation IDs, and structured logging.

Standard library only so every service (worker, enumerator, serving-shim)
composes the same key mapping and log format. Shared via aico_common.
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any
from urllib.parse import urlparse


def new_correlation_id() -> str:
    """A short id threaded through a URL's full journey."""
    return uuid.uuid4().hex[:16]


def path_to_key(path: str) -> str:
    """Map a request path to a storage key: default to index, end in .md.

    ``/`` -> ``/index.md`` · ``/foo`` -> ``/foo.md`` · ``/bar/`` -> ``/bar/index.md``.
    The worker (writer) and the serving-shim (reader) MUST agree on this mapping.
    """
    path = path or "/"
    if path.endswith("/"):
        path = path + "index"
    if not path.startswith("/"):
        path = "/" + path
    return path + ".md"


def url_to_key(url: str) -> str:
    """Map a URL to a storage key (its path via ``path_to_key``)."""
    return path_to_key(urlparse(url).path or "/")


def log_event(correlation_id: str, stage: str, **fields: Any) -> None:
    """Emit one structured JSON log line to stdout (Cloud Logging ingests it)."""
    record: dict[str, Any] = {"correlation_id": correlation_id, "stage": stage}
    record.update({k: v for k, v in fields.items() if v is not None})
    print(json.dumps(record, ensure_ascii=False), file=sys.stdout, flush=True)
