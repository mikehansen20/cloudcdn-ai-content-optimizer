"""Markdown front-matter schema and output contracts.

The core schema provides a universal contract. `type_fields` provides optional type-specific
extensions (product price/sku, article author, etc.). Type-specific facts are validated
before inclusion.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

SCHEMA_VERSION = 1


class ContentType(str, Enum):
    product = "product"
    article = "article"
    faq = "faq"
    listing = "listing"
    generic = "generic"


class ExtractionPath(str, Enum):
    deterministic = "deterministic"
    model = "model"


class FrontMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    url: str
    title: str
    content_type: ContentType
    description: str | None = None
    source_hash: str
    source_validator: str | None = None
    generated_at: datetime
    extraction_path: ExtractionPath
    # Present iff extraction_path == model (provenance must be honest).
    model: str | None = None
    # Open type-specific block (validated facts). Empty for generic pages.
    type_fields: dict[str, Any] = {}

    @model_validator(mode="after")
    def _model_id_matches_path(self) -> "FrontMatter":
        if self.extraction_path is ExtractionPath.model and not self.model:
            raise ValueError("extraction_path=model requires a model id")
        if self.extraction_path is ExtractionPath.deterministic and self.model:
            raise ValueError("extraction_path=deterministic must not carry a model id")
        return self

    def to_metadata_dict(self) -> dict[str, str]:
        """Off-document provenance record for GCS object metadata.

        All values are strings; absent optionals are omitted; type_fields are excluded.
        Object metadata carries system provenance separately from the rendered document.
        """
        data: dict[str, str] = {
            "schema_version": str(self.schema_version),
            "url": self.url,
            "title": self.title,
            "content_type": self.content_type.value,
            "source_hash": self.source_hash,
            "generated_at": self.generated_at.isoformat(),
            "extraction_path": self.extraction_path.value,
        }
        if self.description is not None:
            data["description"] = self.description
        if self.source_validator is not None:
            data["source_validator"] = self.source_validator
        if self.model is not None:
            data["model"] = self.model
        return data
