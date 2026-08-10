"""Validation gate validating model-emitted facts against authoritative source values.

Facts are categorized into numeric facts (compared as float values) and entity/string facts
(compared using token-subset matching after normalization). Uncorroborated facts are dropped.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

# Whole-value numeric forms: optional sign, optional currency, digits/grouping,
# optional decimals, optional percent. Letters anywhere => treated as an entity.
_NUMERIC_RE = re.compile(r"^[+-]?[$€£¥]?\s?[\d,]+(?:\.\d+)?\s?%?$")


def normalize_text(value: Any) -> str:
    """NFKC + strip diacritics + lowercase + drop punctuation + collapse spaces."""
    text = unicodedata.normalize("NFKC", str(value))
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(value: Any) -> set[str]:
    return set(normalize_text(value).split())


def as_number(value: Any) -> float | None:
    """Return the numeric value iff the *whole* string is a number, else None."""
    text = str(value).strip()
    if not _NUMERIC_RE.match(text):
        return None
    cleaned = re.sub(r"[,\s$€£¥%+]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return None


def matches(model_value: Any, source_value: Any) -> bool:
    """True if ``model_value`` is corroborated by ``source_value``."""
    mnum, snum = as_number(model_value), as_number(source_value)
    if mnum is not None and snum is not None:
        return abs(mnum - snum) < 1e-9
    if mnum is not None or snum is not None:
        return False  # one numeric, one not -> not the same fact
    mtok, stok = tokens(model_value), tokens(source_value)
    if not mtok or not stok:
        return False
    # token-subset containment (either direction allows truncation)
    return mtok <= stok or stok <= mtok


def validate_value(model_value: Any, candidates: Iterable[Any]) -> bool:
    """True if any authoritative candidate corroborates ``model_value``."""
    return any(matches(model_value, c) for c in candidates)


@dataclass
class ValidationResult:
    kept: dict[str, Any] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    degrade: bool = False  # a required field failed validation


def apply_validation(
    facts: dict[str, Any],
    candidates: Iterable[Any],
    required: Iterable[str] = (),
) -> ValidationResult:
    """Keep corroborated facts, drop the rest; degrade if a required field drops."""
    candidates = list(candidates)
    required_set = set(required)
    result = ValidationResult()
    for field_name, value in facts.items():
        if validate_value(value, candidates):
            result.kept[field_name] = value
        else:
            result.dropped.append(field_name)
            if field_name in required_set:
                result.degrade = True
    return result
