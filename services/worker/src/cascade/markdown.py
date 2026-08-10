"""Render consumer document: body text formatted with a URL line after the heading.

No YAML front matter in the document text. Formatting uses a plain '# Title'
followed by a '**URL:** ...' line, then content. Metadata (source_hash, model, extraction_path, etc.)
is stored in object metadata during write operations.
"""

from __future__ import annotations

from cascade.schema import FrontMatter


def render_markdown(front_matter: FrontMatter, body: str) -> str:
    """Canonical `# {title}`, a `**URL:**` line, then the body.

    The title comes from the record. If the body leads with its own H1,
    the duplicate H1 is dropped to prevent duplication.
    """
    body = body.strip()
    if body.startswith("# "):
        _, _, body = body.partition("\n")
        body = body.strip()
    parts = [f"# {front_matter.title}", "", f"**URL:** {front_matter.url}"]
    if body:
        parts += ["", body]
    return "\n".join(parts) + "\n"
