"""SSRF-guarded conditional fetch.

Fetches a URL with a distinctive, allowlistable crawler User-Agent. The crawler
uses an honest User-Agent allowing WAF/CDN configurations to allowlist it (see docs/INTEGRATION_GUIDE.md).
The same User-Agent is excluded by the edge plugin loop-guard to prevent circular fetching.
Supports conditional GET where a stored validator (ETag or Last-Modified) yields a 304 response when unchanged.
200 responses return the body, a fresh validator, and a SHA-256 hash of the body for change detection.
SSRF guards run before fetching. DNS resolution and HTTP transport are injectable for offline testing.
"""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping

from aico_common.ssrf import Resolver, assert_safe_url

# Distinctive, allowlistable crawler identity (carries a GCP / Cloud CDN marker).
# Overridable per deployment via the CRAWLER_USER_AGENT env var (wired by Terraform).
CRAWLER_UA = "AIContentOptimizer/1.0 (GCP Cloud CDN content optimizer)"


@dataclass
class Validator:
    """Origin change-detection validators, echoed back on the next fetch."""

    etag: str | None = None
    last_modified: str | None = None

    def is_empty(self) -> bool:
        return not (self.etag or self.last_modified)


@dataclass
class Response:
    """Raw transport response (status, headers, body bytes)."""

    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, Mapping[str, str]], Response]


@dataclass
class FetchResult:
    status: int
    html: str | None = None
    validator: Validator | None = None
    body_hash: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def unchanged(self) -> bool:
        return self.status == 304


def _ci(headers: Mapping[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in dict(headers).items()}


def fetch(
    url: str,
    *,
    validator: Validator | None = None,
    allowed_hosts=None,
    resolve: Resolver | None = None,
    transport: Transport | None = None,
    user_agent: str = CRAWLER_UA,
    extra_headers: Mapping[str, str] | None = None,
) -> FetchResult:
    """Conditionally GET ``url`` behind the SSRF guard.

    ``extra_headers`` are added verbatim (e.g. the serving-shim's ``X-From-LLM-Optimizer``
    loop-guard on its origin proxy fetch).
    """
    assert_safe_url(url, allowed_hosts=allowed_hosts, resolve=resolve)

    transport = transport or _urllib_transport
    headers = {"User-Agent": user_agent}
    if extra_headers:
        headers.update(extra_headers)
    if validator:
        if validator.etag:
            headers["If-None-Match"] = validator.etag
        if validator.last_modified:
            headers["If-Modified-Since"] = validator.last_modified

    resp = transport(url, headers)

    if resp.status == 304:
        return FetchResult(status=304)
    if resp.status == 200:
        rh = _ci(resp.headers)
        return FetchResult(
            status=200,
            html=resp.body.decode("utf-8", errors="replace"),
            validator=Validator(etag=rh.get("etag"), last_modified=rh.get("last-modified")),
            body_hash=hashlib.sha256(resp.body).hexdigest(),
        )
    # 3xx responses (not followed because a redirect could target an unvalidated host;
    # caller re-guards and refetches), 4xx (including 403), and 5xx responses.
    return FetchResult(status=resp.status)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # never auto-follow (SSRF safety)


def _urllib_transport(url: str, headers: Mapping[str, str]) -> Response:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=20) as r:
            return Response(status=r.status, headers=dict(r.headers), body=r.read())
    except urllib.error.HTTPError as exc:
        # urllib raises for non-200/304 status codes. Surface the status code to the caller.
        body = exc.read() if exc.fp is not None else b""
        return Response(status=exc.code, headers=dict(exc.headers or {}), body=body)
    except urllib.error.URLError:
        # Connection-level failure (DNS/route/timeout) representing a non-ok result.
        return Response(status=0, headers={}, body=b"")
