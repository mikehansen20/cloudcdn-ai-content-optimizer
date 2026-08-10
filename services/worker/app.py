"""Worker service processing URLs into optimized Markdown storage.

Accepts POST /process requests: performs conditional SSRF-guarded fetch, executes cascade extraction
(using RemoteRenderer and ModelClient), and writes output to storage. Idempotent operations skip model execution
when source hashes are unchanged. Pub/Sub push requests and direct HTTP requests use the same payload format.

All I/O components use FastAPI dependencies for offline testability.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from aico_common.fetch import CRAWLER_UA, Validator, fetch as aico_fetch
from aico_common.ssrf import SsrfError
from cascade.cascade import run_cascade
from cascade.model import StubModelClient
from cascade.render import RemoteRenderer
from aico_common.service_support import log_event, new_correlation_id, url_to_key
from aico_common.storage import LocalStorage, Storage

app = FastAPI(title="AI Content Optimizer: Worker")


@dataclass
class Settings:
    storage_backend: str  # "local" | "gcs"
    storage_dir: str
    gcs_bucket: str | None
    allowed_hosts: tuple[str, ...] | None
    renderer_url: str | None
    renderer_auth: bool
    model: str            # "stub" | "vertex"
    project: str
    location: str
    model_id: str
    crawler_user_agent: str = CRAWLER_UA


def get_settings() -> Settings:
    hosts = os.environ.get("SITE_HOSTS", "").strip()
    return Settings(
        storage_backend=os.environ.get("STORAGE", "local"),
        storage_dir=os.environ.get("STORAGE_DIR", "/tmp/aico-output"),
        gcs_bucket=os.environ.get("GCS_BUCKET") or None,
        allowed_hosts=tuple(h.strip() for h in hosts.split(",") if h.strip()) or None,
        renderer_url=os.environ.get("RENDERER_URL") or None,
        renderer_auth=os.environ.get("RENDERER_AUTH", "").lower() in ("1", "true", "yes"),
        model=os.environ.get("MODEL", "stub"),
        project=os.environ.get("GCP_PROJECT", ""),
        location=os.environ.get("VERTEX_LOCATION", "us-central1"),
        model_id=os.environ.get("MODEL_ID", "gemini-3.5-flash"),
        crawler_user_agent=os.environ.get("CRAWLER_USER_AGENT") or CRAWLER_UA,
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


def get_model_client(settings: Settings = Depends(get_settings)):
    if settings.model == "vertex":
        from cascade.model_vertex import VertexModelClient

        return VertexModelClient(project=settings.project, location=settings.location,
                                 model_id=settings.model_id)
    return StubModelClient()


def get_renderer(settings: Settings = Depends(get_settings)):
    if not settings.renderer_url:
        return None
    return RemoteRenderer(settings.renderer_url, use_auth=settings.renderer_auth)


class ProcessRequest(BaseModel):
    url: str


class ProcessResponse(BaseModel):
    url: str
    key: str
    outcome: str  # generated | unchanged | unchanged-304
    content_type: str | None = None
    extraction_path: str | None = None
    rendered: bool = False


class PubSubMessage(BaseModel):
    data: str  # base64-encoded


class PubSubEnvelope(BaseModel):
    message: PubSubMessage
    subscription: str | None = None


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/process", response_model=ProcessResponse)
def process(
    req: ProcessRequest,
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    fetch=Depends(get_fetch),
    model=Depends(get_model_client),
    renderer=Depends(get_renderer),
) -> ProcessResponse:
    return _run(req.url, new_correlation_id(), settings, storage, fetch, model, renderer)


@app.post("/pubsub")
def pubsub(
    envelope: PubSubEnvelope,
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    fetch=Depends(get_fetch),
    model=Depends(get_model_client),
    renderer=Depends(get_renderer),
) -> dict:
    """Pub/Sub push target. 2xx acks; 5xx nacks (retry -> dead-letter).
    A message that can never be processed (malformed / unsafe url) is acked."""
    import base64
    import json

    cid = new_correlation_id()
    try:
        payload = json.loads(base64.b64decode(envelope.message.data))
        url = payload["url"]
    except Exception as exc:  # unparseable -> ack (retrying can't fix it)
        log_event(cid, "pubsub", outcome="bad-message", error=str(exc))
        return {"status": "bad-message"}

    try:
        result = _run(url, cid, settings, storage, fetch, model, renderer)
    except HTTPException as exc:
        if exc.status_code < 500:  # unprocessable (e.g., SSRF) -> ack, don't retry forever
            log_event(cid, "pubsub", outcome="unprocessable", status=exc.status_code)
            return {"status": "unprocessable"}
        raise  # 5xx -> nack -> Pub/Sub retry -> dead-letter
    return {"status": result.outcome, "key": result.key}


def _run(url, cid, settings, storage, fetch, model, renderer) -> ProcessResponse:
    key = url_to_key(url)
    log_event(cid, "start", url=url, key=key)

    prior = storage.get_metadata(key)
    validator = None
    if prior.get("etag") or prior.get("last_modified"):
        validator = Validator(etag=prior.get("etag") or None,
                              last_modified=prior.get("last_modified") or None)

    try:
        result = fetch(url, validator=validator, allowed_hosts=settings.allowed_hosts,
                       user_agent=settings.crawler_user_agent)
    except SsrfError as exc:
        log_event(cid, "fetch", outcome="ssrf-blocked", error=str(exc))
        raise HTTPException(status_code=400, detail=f"unsafe url: {exc}")

    if result.unchanged:
        log_event(cid, "fetch", outcome="304-unchanged")
        return ProcessResponse(url=url, key=key, outcome="unchanged-304")
    if not result.ok:
        log_event(cid, "fetch", outcome=f"http-{result.status}")
        raise HTTPException(status_code=502, detail=f"fetch failed: HTTP {result.status}")
    if prior.get("source_hash") and prior["source_hash"] == result.body_hash:
        log_event(cid, "hash", outcome="unchanged")  # Idempotent skip without model call
        return ProcessResponse(url=url, key=key, outcome="unchanged")

    validator_str = None
    if result.validator:
        validator_str = result.validator.etag or result.validator.last_modified

    cascade_result = run_cascade(
        result.html, url, model_client=model, renderer=renderer,
        source_hash=result.body_hash, source_validator=validator_str,
    )

    # Object metadata is the off-document provenance record: full front-matter
    # contract (title/url/description/content_type/extraction_path/source_hash/
    # model/generated_at) plus the HTTP validators. None of it is in the document.
    metadata = cascade_result.front_matter.to_metadata_dict()
    metadata["etag"] = (result.validator.etag if result.validator else "") or ""
    metadata["last_modified"] = (result.validator.last_modified if result.validator else "") or ""
    storage.write(key, cascade_result.markdown, metadata)
    storage.delete("/pending" + key)  # clear the serving-shim's self-heal marker
    log_event(cid, "done", outcome="generated", content_type=metadata["content_type"],
              extraction_path=metadata["extraction_path"], model=metadata.get("model"),
              rendered=cascade_result.rendered)

    return ProcessResponse(
        url=url, key=key, outcome="generated",
        content_type=metadata["content_type"],
        extraction_path=metadata["extraction_path"],
        rendered=cascade_result.rendered,
    )
