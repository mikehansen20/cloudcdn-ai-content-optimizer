"""Renderer service hosting POST /render endpoint to return painted DOM HTML.

FastAPI application wrapping headless Chromium, protected by SSRF validation.
Internal service invoked by the worker RemoteRenderer client.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from aico_common.ssrf import SsrfError, assert_safe_url
from browser import PlaywrightRenderer

app = FastAPI(title="AI Content Optimizer: Renderer")

_renderer = PlaywrightRenderer()


def get_renderer() -> PlaywrightRenderer:
    return _renderer


def get_resolver():
    return None  # default: real DNS (overridden in tests for offline determinism)


class RenderRequest(BaseModel):
    url: str


class RenderResponse(BaseModel):
    html: str


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/render", response_model=RenderResponse)
def render(req: RenderRequest, renderer=Depends(get_renderer), resolve=Depends(get_resolver)) -> RenderResponse:
    try:
        assert_safe_url(req.url, resolve=resolve)
    except SsrfError as exc:
        raise HTTPException(status_code=400, detail=f"unsafe url: {exc}")
    try:
        html = renderer.render(req.url)
    except Exception as exc:  # a browser crash must be a clean 502, not a 500 stack
        raise HTTPException(status_code=502, detail=f"render failed: {exc}")
    return RenderResponse(html=html)
