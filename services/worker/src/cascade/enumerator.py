"""Sitemap enumerator parsing sitemaps into per-URL messages.

Fetches the sitemap (using injected SSRF-guarded fetcher), parses XML (including
sitemap index recursion), filters URLs via include and exclude glob patterns, and publishes
one message per URL. Designed for offline testing and Cloud Run execution.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Callable, Iterator, Mapping, Protocol, runtime_checkable
from urllib.parse import urlparse

from aico_common.pubsub import PubSubPublisher  # canonical location; re-exported here


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_loc(element) -> str | None:
    for child in element:
        if _localname(child.tag) == "loc" and child.text:
            return child.text.strip()
    return None


def parse_sitemap(xml: str) -> tuple[list[str], list[str]]:
    """Return (page_urls, sub_sitemap_urls). A ``sitemapindex`` yields sub-sitemaps."""
    root = ET.fromstring(xml)
    pages: list[str] = []
    subs: list[str] = []
    is_index = _localname(root.tag) == "sitemapindex"
    for entry in root:
        loc = _find_loc(entry)
        if not loc:
            continue
        (subs if is_index else pages).append(loc)
    return pages, subs


def matches_globs(url: str, include, exclude) -> bool:
    """Path-glob filter: exclude wins; with no include, everything not excluded passes."""
    path = urlparse(url).path or "/"
    if exclude and any(fnmatch(path, g) for g in exclude):
        return False
    if include:
        return any(fnmatch(path, g) for g in include)
    return True


def enumerate_urls(
    sitemap_url: str,
    *,
    fetch: Callable,
    include=None,
    exclude=None,
    allowed_hosts=None,
    max_depth: int = 5,
    _depth: int = 0,
) -> Iterator[str]:
    """Yield filtered page URLs from a sitemap, recursing into sitemap indexes."""
    result = fetch(sitemap_url, allowed_hosts=allowed_hosts)
    if not getattr(result, "ok", False) or not getattr(result, "html", None):
        return
    pages, subs = parse_sitemap(result.html)
    for url in pages:
        if matches_globs(url, include, exclude):
            yield url
    if _depth < max_depth:
        for sub in subs:
            yield from enumerate_urls(
                sub, fetch=fetch, include=include, exclude=exclude,
                allowed_hosts=allowed_hosts, max_depth=max_depth, _depth=_depth + 1,
            )


@runtime_checkable
class Publisher(Protocol):
    def publish(self, url: str) -> None: ...


def run_enumerator(sitemap_url: str, publisher: Publisher, **kwargs) -> int:
    """Enumerate + publish; return the number of URLs published."""
    count = 0
    for url in enumerate_urls(sitemap_url, **kwargs):
        publisher.publish(url)
        count += 1
    return count


# --- Cloud Run job entrypoint (Scheduler-triggered) ---

@dataclass
class EnumeratorConfig:
    """Config for a single enumerator run, assembled from the job's env."""

    sitemap_url: str
    project: str
    topic: str
    include: list[str]
    exclude: list[str]
    allowed_hosts: tuple[str, ...] | None


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def config_from_env(env: Mapping[str, str]) -> EnumeratorConfig:
    """Build an EnumeratorConfig from env vars (mirrors the worker's conventions).

    SITEMAP_URL wins; otherwise it defaults to <SITE_BASE_URL>/sitemap.xml.
    """
    sitemap = (env.get("SITEMAP_URL") or "").strip()
    base = (env.get("SITE_BASE_URL") or "").strip()
    if not sitemap:
        if not base:
            raise ValueError("set SITEMAP_URL or SITE_BASE_URL")
        sitemap = base.rstrip("/") + "/sitemap.xml"
    hosts = _split_csv(env.get("SITE_HOSTS", ""))
    return EnumeratorConfig(
        sitemap_url=sitemap,
        project=env.get("GCP_PROJECT", ""),
        topic=env.get("CRAWL_TOPIC", "ai-optimizer-crawl"),
        include=_split_csv(env.get("INCLUDE_PATHS", "")),
        exclude=_split_csv(env.get("EXCLUDE_PATHS", "")),
        allowed_hosts=tuple(hosts) or None,
    )


def main(argv=None, *, env: Mapping[str, str] | None = None,
         fetch: Callable | None = None, publisher: Publisher | None = None) -> int:
    """Enumerate the configured sitemap and publish one crawl message per URL."""
    env = env if env is not None else os.environ
    cfg = config_from_env(env)
    if fetch is None:
        from aico_common.fetch import fetch as _fetch
        ua = (env.get("CRAWLER_USER_AGENT") or "").strip()
        # Keep the sitemap fetch's identity consistent with the worker's page fetch,
        # so a customized crawler UA is allowlistable across both (else the default applies).
        fetch = (lambda url, **kw: _fetch(url, user_agent=ua, **kw)) if ua else _fetch
    if publisher is None:
        publisher = PubSubPublisher(cfg.project, cfg.topic)
    print(f"[ENUMERATOR] Fetching sitemap: {cfg.sitemap_url}", flush=True)
    count = run_enumerator(
        cfg.sitemap_url, publisher, fetch=fetch,
        include=cfg.include or None, exclude=cfg.exclude or None,
        allowed_hosts=cfg.allowed_hosts,
    )
    if hasattr(publisher, "flush"):
        publisher.flush()  # confirm delivery before the job exits (else batches drop)
    print(f"[ENUMERATOR] Parsed sitemap: {count} URLs discovered. Published {count} crawl messages to Pub/Sub topic '{cfg.topic}'.", flush=True)
    print(json.dumps({"stage": "enumerate", "sitemap": cfg.sitemap_url,
                      "published": count}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
