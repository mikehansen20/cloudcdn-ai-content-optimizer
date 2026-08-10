"""Deterministic structured-data harvest.

Extracts authoritative facts from a page. Starts with JSON-LD (the dominant
signal); microdata / OpenGraph / meta are added in later slices. Harvested facts
are treated as authoritative and ground the model when the gate escalates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

from bs4 import BeautifulSoup


@dataclass
class Harvest:
    """Structured facts extracted from a page."""

    json_ld: list[dict] = field(default_factory=list)

    @property
    def types(self) -> set[str]:
        """The set of schema.org @type values present across all objects."""
        found: set[str] = set()
        for obj in self.json_ld:
            found.update(_types_of(obj))
        return found

    def first_of_type(self, type_name: str) -> dict | None:
        """The first harvested object declaring ``type_name`` as an @type."""
        for obj in self.json_ld:
            if type_name in _types_of(obj):
                return obj
        return None

    def all_of_type(self, type_name: str) -> list[dict]:
        """Every harvested object declaring ``type_name`` as an @type."""
        return [obj for obj in self.json_ld if type_name in _types_of(obj)]


def deep_find(obj: Any, keys: Iterable[str]) -> Any:
    """First non-empty value for any of ``keys``, searching nested dicts/lists."""
    keyset = set(keys)
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keyset and value not in (None, "", [], {}):
                return value
        for value in obj.values():
            found = deep_find(value, keyset)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = deep_find(item, keyset)
            if found is not None:
                return found
    return None


def _types_of(obj: dict) -> list[str]:
    raw = obj.get("@type")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw]
    return [str(raw)]


def _iter_objects(payload: Any) -> Iterator[dict]:
    """Yield every typed node (any dict with ``@type``) at any depth.

    Real pages nest entities: a ``ProductGroup`` carries ``Product`` variants under ``hasVariant``,
    and a ``CollectionPage`` nests an ``ItemList`` under ``mainEntity``. A single generic walk
    yields any dict declaring an ``@type``, then recurses into nested dict and list values.
    """
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_objects(item)
    elif isinstance(payload, dict):
        if payload.get("@type") is not None:
            yield payload
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from _iter_objects(value)


def harvest_structured_data(html: str) -> Harvest:
    """Parse ``html`` and return the harvested structured data."""
    soup = BeautifulSoup(html, "lxml")
    objects: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (script.get_text() or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except ValueError:
            # A malformed block must not sink the whole harvest.
            continue
        for obj in _iter_objects(payload):
            if isinstance(obj, dict):
                objects.append(obj)
    return Harvest(json_ld=objects)
