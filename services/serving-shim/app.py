"""Serving shim service operating at CDN origin for AI crawler paths.

Routes, proxies, and enqueues requests. The edge plugin rewrites AI crawler paths
to `${ai_path_prefix}/<original>` which routes to this service.

- GCS object present: serves pre-generated Markdown with a cacheable TTL.
- GCS object absent: proxies origin HTML with no-store headers and loop-guard, and enqueues jobs via pending markers.

All I/O uses FastAPI dependencies for offline testability.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Depends, FastAPI, Response

from aico_common.fetch import fetch as aico_fetch
from aico_common.pubsub import PubSubPublisher
from aico_common.service_support import log_event, new_correlation_id, path_to_key
from aico_common.ssrf import SsrfError
from aico_common.storage import LocalStorage, Storage

app = FastAPI(title="AI Content Optimizer: Serving Shim")

LOOP_GUARD_HEADER = "X-From-LLM-Optimizer"

# Root-level static index files (mirroring llms builder keys). Served to all clients
# as plain text without Markdown mapping or self-healing.
LLMS_PATHS = {"/llms.txt", "/llms-full.txt"}


@dataclass
class Settings:
    storage_backend: str  # "local" | "gcs"
    storage_dir: str
    gcs_bucket: str | None
    ai_path_prefix: str
    content_cache_ttl: int
    site_base_url: str
    allowed_hosts: tuple[str, ...] | None
    origin_404_behavior: str  # "proxy_and_generate" | "notfound"
    project: str
    crawl_topic: str


def get_settings() -> Settings:
    hosts = os.environ.get("SITE_HOSTS", "").strip()
    return Settings(
        storage_backend=os.environ.get("STORAGE", "local"),
        storage_dir=os.environ.get("STORAGE_DIR", "/tmp/aico-output"),
        gcs_bucket=os.environ.get("GCS_BUCKET") or None,
        ai_path_prefix=os.environ.get("AI_PATH_PREFIX", "/_ai_optimized"),
        content_cache_ttl=int(os.environ.get("CONTENT_CACHE_TTL", "3600")),
        site_base_url=os.environ.get("SITE_BASE_URL", ""),
        allowed_hosts=tuple(h.strip() for h in hosts.split(",") if h.strip()) or None,
        origin_404_behavior=os.environ.get("ORIGIN_404_BEHAVIOR", "proxy_and_generate"),
        project=os.environ.get("GCP_PROJECT", ""),
        crawl_topic=os.environ.get("CRAWL_TOPIC", "ai-optimizer-crawl"),
    )


def get_storage(settings: Settings = Depends(get_settings)) -> Storage:
    if settings.storage_backend == "gcs":
        from aico_common.gcs_storage import GcsStorage

        if not settings.gcs_bucket:
            raise RuntimeError("STORAGE=gcs requires GCS_BUCKET")
        return GcsStorage(settings.gcs_bucket)
    return LocalStorage(settings.storage_dir)


def get_fetch():
    return aico_fetch


def get_publisher(settings: Settings = Depends(get_settings)) -> PubSubPublisher:
    return PubSubPublisher(settings.project, settings.crawl_topic)


def _original_path(full_path: str, prefix: str) -> str:
    """Recover the original request path from ``${ai_path_prefix}/<original>``.

    Robust to whether the customer's URL map strips the prefix before forwarding: if the
    prefix is already gone, stripping is a no-op.
    """
    path = "/" + full_path  # FastAPI drops the leading slash from a path param
    if prefix and path.startswith(prefix):
        path = path[len(prefix):]
    return path or "/"


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/{full_path:path}")
def serve(
    full_path: str,
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    fetch=Depends(get_fetch),
    publisher: PubSubPublisher = Depends(get_publisher),
) -> Response:
    cid = new_correlation_id()
    original = _original_path(full_path, settings.ai_path_prefix)
    is_index = original in LLMS_PATHS
    key = original if is_index else path_to_key(original)
    media_type = "text/plain; charset=utf-8" if is_index else "text/markdown"
    log_event(cid, "serve", path=original, key=key)

    # Present → serve the pre-generated, cacheable content.
    if storage.exists(key):
        log_event(cid, "serve", outcome="hit", key=key)
        return Response(
            content=storage.read(key),
            media_type=media_type,
            headers={"Cache-Control": f"public, max-age={settings.content_cache_ttl}"},
        )

    # A missing index file returns 404 without origin proxying or job enqueueing.
    if is_index:
        log_event(cid, "serve", outcome="miss-index-404", key=key)
        return Response(status_code=404)

    # Absent content self-healing.
    if settings.origin_404_behavior == "notfound":
        log_event(cid, "serve", outcome="miss-404", key=key)
        return Response(status_code=404)

    origin_url = settings.site_base_url.rstrip("/") + original
    # (a) Proxy origin HTML with loop-guard header (so the edge plugin skips this fetch)
    # and SSRF protection. Returns content directly without 302 redirects.
    try:
        result = fetch(origin_url, allowed_hosts=settings.allowed_hosts,
                       extra_headers={LOOP_GUARD_HEADER: "1"})
    except SsrfError as exc:
        log_event(cid, "serve", outcome="ssrf-blocked", error=str(exc))
        return Response(status_code=502, headers={"Cache-Control": "no-store"})

    # (b) Asynchronous enqueue deduplicated via atomic pending markers.
    if storage.create_if_absent("/pending" + key):
        publisher.publish(origin_url)
        publisher.flush()
        log_event(cid, "serve", outcome="enqueued", key=key)
    else:
        log_event(cid, "serve", outcome="miss-pending", key=key)

    # Return proxied HTML with no-store cache headers so un-optimized fallback is not cached.
    return Response(
        content=result.html or "",
        status_code=result.status if result.status else 502,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )
