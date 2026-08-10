"""Shared HTML to text extraction helper for model input and content validation."""

from __future__ import annotations

from bs4 import BeautifulSoup


def extract_text(html: str) -> str:
    """Visible text with chrome/scripts stripped."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)
