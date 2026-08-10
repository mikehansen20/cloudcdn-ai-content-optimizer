"""Deterministic HTML to clean Markdown body extractor.

Converts main page content HTML into structured Markdown without model calls.
Strips boilerplate, navigation, footers, scripts, and non-content elements.
"""

from __future__ import annotations

import re
from typing import Set

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

NOISE_TAGS = {
    "script", "style", "noscript", "template", "svg", "canvas", "iframe",
    "form", "input", "button", "select", "dialog", "nav", "header",
    "footer", "aside", "menu",
}

NOISE_ROLES = {"navigation", "banner", "contentinfo", "search", "dialog", "complementary"}


def extract_body_markdown(html: str, exclude_headings: Set[str] | None = None) -> str:
    """Convert HTML DOM content into clean, readable Markdown."""
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "lxml")
    exclude_headings = {h.strip().lower() for h in (exclude_headings or set()) if h}

    # 1. Strip comments and noise tags
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()

    for tag in soup.find_all(list(NOISE_TAGS)):
        tag.decompose()

    # 2. Strip elements with noise roles or hidden styling
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        role = (tag.get("role") or "").lower()
        if role in NOISE_ROLES:
            tag.decompose()
            continue
        if tag.has_attr("hidden") or tag.get("aria-hidden") == "true":
            tag.decompose()
            continue
        style = (tag.get("style") or "").lower()
        if "display:none" in style.replace(" ", "") or "visibility:hidden" in style.replace(" ", ""):
            tag.decompose()
            continue

    # 3. Target main content area if available
    root = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.find(id=re.compile(r"^(main-content|main|content|product-detail.*|item-detail.*)$", re.I))
        or soup.find(class_=re.compile(r"(main-content|product-description|product-details|entry-content|article-body)", re.I))
        or soup.body
        or soup
    )

    lines: list[str] = []
    _render_node(root, lines, exclude_headings)

    raw_md = "\n".join(lines)
    # Collapse multiple blank lines
    raw_md = re.sub(r"\n{3,}", "\n\n", raw_md)
    return raw_md.strip()


def _render_node(node, lines: list[str], exclude_headings: Set[str]) -> None:
    if isinstance(node, NavigableString):
        text = str(node).strip()
        if text:
            lines.append(text)
        return

    if not isinstance(node, Tag):
        return

    name = node.name.lower()

    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(name[1])
        text = _inline_text(node).strip()
        if text and text.lower() not in exclude_headings:
            prefix = "#" * level
            lines.append(f"{prefix} {text}")
            lines.append("")
        return

    if name == "p":
        text = _inline_text(node).strip()
        if text:
            lines.append(text)
            lines.append("")
        return

    if name in {"ul", "ol"}:
        is_ordered = name == "ol"
        idx = 1
        for li in node.find_all("li", recursive=False):
            li_text = _inline_text(li).strip()
            if li_text:
                if is_ordered:
                    lines.append(f"{idx}. {li_text}")
                    idx += 1
                else:
                    lines.append(f"- {li_text}")
        lines.append("")
        return

    if name == "table":
        table_lines = _render_table(node)
        if table_lines:
            lines.extend(table_lines)
            lines.append("")
        return

    if name == "blockquote":
        b_text = _inline_text(node).strip()
        if b_text:
            for b_line in b_text.splitlines():
                lines.append(f"> {b_line}")
            lines.append("")
        return

    if name == "pre":
        code_text = node.get_text()
        lines.append(f"```\n{code_text.strip()}\n```")
        lines.append("")
        return

    if name == "hr":
        lines.append("---")
        lines.append("")
        return

    if name == "br":
        lines.append("")
        return

    # Recurse children for container tags (div, section, span, etc.)
    for child in node.children:
        _render_node(child, lines, exclude_headings)


def _render_table(table: Tag) -> list[str]:
    rows = table.find_all("tr")
    if not rows:
        return []

    grid: list[list[str]] = []
    for r in rows:
        cells = r.find_all(["th", "td"])
        row_vals = [_inline_text(c).strip().replace("|", "\\|") for c in cells]
        if any(row_vals):
            grid.append(row_vals)

    if not grid:
        return []

    # Standardize column count
    num_cols = max(len(r) for r in grid)
    if num_cols == 0:
        return []

    padded = [r + [""] * (num_cols - len(r)) for r in grid]
    header = padded[0]
    separator = ["---"] * num_cols

    res = [f"| {' | '.join(header)} |", f"|{'|'.join(separator)}|"]
    for row in padded[1:]:
        res.append(f"| {' | '.join(row)} |")
    return res


def _inline_text(tag: Tag) -> str:
    """Format inline formatting elements like links, bold, code within a tag."""
    parts = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            c_name = child.name.lower()
            inner = _inline_text(child)
            if c_name in {"strong", "b"}:
                parts.append(f"**{inner.strip()}**" if inner.strip() else "")
            elif c_name in {"em", "i"}:
                parts.append(f"*{inner.strip()}*" if inner.strip() else "")
            elif c_name == "code":
                parts.append(f"`{inner.strip()}`" if inner.strip() else "")
            elif c_name == "a":
                href = (child.get("href") or "").strip()
                t = inner.strip()
                if href and t and not href.startswith("javascript:") and not href.startswith("#"):
                    parts.append(f"[{t}]({href})")
                elif t:
                    parts.append(t)
            elif c_name == "br":
                parts.append("\n")
            else:
                parts.append(inner)
    return "".join(parts)
