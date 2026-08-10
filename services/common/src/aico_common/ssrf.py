"""SSRF fetch-guard validating all outbound requests.

Imported by the worker fetcher, serving-shim, and renderer origin proxy. Rejects any URL
whose host is not allowlisted or resolves to a non-public IP (private/link-local/metadata/loopback/reserved).
DNS resolution is injectable for deterministic offline testing.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import urlparse

Resolver = Callable[[str], list[str]]


class SsrfError(ValueError):
    """Raised when a URL is unsafe to fetch."""


def _default_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local       # covers 169.254.0.0/16 incl. the cloud metadata IP
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_safe_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    resolve: Resolver | None = None,
) -> None:
    """Raise ``SsrfError`` unless ``url`` is safe to fetch.

    - scheme must be http/https and a host must be present;
    - if ``allowed_hosts`` is given, the host must be in it (case-insensitive);
    - every resolved IP must be public (reject DNS-rebinding to a private IP).
    """
    resolve = resolve or _default_resolve
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise SsrfError(f"unsupported scheme: {parsed.scheme!r}")

    host = (parsed.hostname or "").lower()
    if not host:
        raise SsrfError("missing host")

    if allowed_hosts is not None:
        allowed = {h.lower() for h in allowed_hosts}
        if host not in allowed:
            raise SsrfError(f"host {host!r} not in allow-list")

    try:
        ips = resolve(host)
    except OSError as exc:
        raise SsrfError(f"could not resolve host {host!r}") from exc
    if not ips:
        raise SsrfError(f"host {host!r} resolved to no addresses")

    for ip in ips:
        if not _is_public(ip):
            raise SsrfError(f"host {host!r} resolves to non-public IP {ip}")
