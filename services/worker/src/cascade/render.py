"""Render fallback module for client-rendered pages.

Evaluates whether a page is an unrendered JavaScript shell. If text content falls below threshold,
renders page with headless Chromium to extract painted DOM HTML. Sits behind the Renderer protocol interface.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Callable, Protocol, runtime_checkable

from cascade.textutil import extract_text

# Below this many characters of visible text, treat the page as an unrendered shell.
MIN_CONTENT_CHARS = 200


def has_meaningful_content(html: str, min_chars: int = MIN_CONTENT_CHARS) -> bool:
    """True if the page already has real content (no render needed)."""
    return len(extract_text(html)) >= min_chars


@runtime_checkable
class Renderer(Protocol):
    def render(self, url: str) -> str:
        """Return the painted DOM HTML for ``url``."""
        ...


def _default_post(url: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    request = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _fetch_id_token(audience: str) -> str:
    """Mint a Google-signed ID token for ``audience`` (Cloud Run service-to-service)."""
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return id_token.fetch_id_token(Request(), audience)


class RemoteRenderer:
    """HTTP client for remote renderer service implementing Renderer protocol."""

    def __init__(
        self,
        base_url: str,
        *,
        post: Callable[..., dict] | None = None,
        timeout: float = 30.0,
        use_auth: bool = False,
        id_token_fn: Callable[[str], str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._post = post or _default_post
        self.timeout = timeout
        self.use_auth = use_auth
        self._id_token_fn = id_token_fn or _fetch_id_token

    def render(self, url: str) -> str:
        headers: dict = {}
        if self.use_auth:
            headers["Authorization"] = f"Bearer {self._id_token_fn(self.base_url)}"
        result = self._post(f"{self.base_url}/render", {"url": url}, self.timeout, headers)
        return result["html"]


class PlaywrightRenderer:
    """Headless Chromium renderer for rendering client-side JavaScript pages."""

    def __init__(self, *, timeout_ms: int = 15000, wait_until: str = "networkidle"):
        self.timeout_ms = timeout_ms
        self.wait_until = wait_until

    def render(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError(
                "playwright is not installed. Install it + a browser "
                "(`pip install playwright && python -m playwright install chromium`) "
                "to render JS-shell pages; the cascade runs without it otherwise."
            ) from exc
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(url, wait_until=self.wait_until, timeout=self.timeout_ms)
                return page.content()
            finally:
                browser.close()
