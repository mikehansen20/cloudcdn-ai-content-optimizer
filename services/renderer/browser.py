"""Headless Chromium rendering module isolated within the renderer service.

Self-contained with lazy Playwright imports so the renderer service requires only Playwright,
FastAPI, and SSRF validation components.
"""

from __future__ import annotations


class PlaywrightRenderer:
    def __init__(self, *, timeout_ms: int = 15000, wait_until: str = "networkidle"):
        self.timeout_ms = timeout_ms
        self.wait_until = wait_until

    def render(self, url: str) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(url, wait_until=self.wait_until, timeout=self.timeout_ms)
                return page.content()
            finally:
                browser.close()
