"""Model client protocol and offline stub implementation.

Cascade depends on the ``ModelClient`` protocol. ``StubModelClient`` derives output
solely from provided input, enabling offline testing. The Vertex client implements the same protocol.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from cascade.schema import ContentType


class ModelOutput(BaseModel):
    """Schema-constrained extraction result (mirrors the output contract)."""

    title: str
    description: str | None = None
    body_markdown: str
    type_fields: dict[str, Any] = {}


@runtime_checkable
class ModelClient(Protocol):
    model_id: str  # recorded in front-matter provenance when the model path is taken

    def extract(self, *, dom_text: str, grounding: dict, content_type: ContentType) -> ModelOutput:
        """Reformat/extract from ``dom_text``, grounded by harvested facts."""
        ...


def _first_nonempty_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


class StubModelClient:
    """Deterministic offline stand-in: echoes input, invents nothing."""

    model_id = "stub"

    def extract(self, *, dom_text: str, grounding: dict, content_type: ContentType) -> ModelOutput:
        title = grounding.get("title") or _first_nonempty_line(dom_text) or "Untitled"
        return ModelOutput(
            title=title,
            description=grounding.get("description"),
            body_markdown=dom_text.strip(),
            type_fields=dict(grounding.get("facts", {})),
        )
