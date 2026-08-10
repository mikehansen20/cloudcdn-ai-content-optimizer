"""Completeness gate evaluation.

Evaluates structured data exposed on a page. Detects content types and checks whether
harvested facts are machine-complete for that type. If complete, formats output deterministically
without model calls; otherwise escalates to the model. Generic content types always escalate.
"""

from __future__ import annotations

from dataclasses import dataclass

from cascade.harvest import Harvest, deep_find
from cascade.schema import ContentType, ExtractionPath

# Minimum threshold for listing items.
MIN_LIST_ITEMS = 3

# Top-level attribute keys that count toward "≥3 structured attributes" for a product.
_PRODUCT_ATTRS = ("brand", "sku", "gtin", "gtin13", "mpn", "color", "size", "material", "model")


@dataclass
class GateDecision:
    content_type: ContentType
    path: ExtractionPath  # deterministic | model (model == "escalate")
    reason: str


def decide(harvest: Harvest) -> GateDecision:
    ctype = _detect_type(harvest)
    checker = {
        ContentType.product: _product_complete,
        ContentType.listing: _listing_complete,
        ContentType.article: _article_complete,
        ContentType.faq: _faq_complete,
    }.get(ctype)
    if checker is None:  # generic
        return GateDecision(ContentType.generic, ExtractionPath.model,
                            "no structured type; generic always escalates")
    complete, reason = checker(harvest)
    path = ExtractionPath.deterministic if complete else ExtractionPath.model
    return GateDecision(ctype, path, reason)


def _detect_type(h: Harvest) -> ContentType:
    """Detection precedence: product > listing > article > faq > generic."""
    t = h.types
    if t & {"Product", "ProductGroup"}:
        return ContentType.product
    if t & {"ItemList", "CollectionPage"}:
        return ContentType.listing
    if t & {"Article", "NewsArticle", "BlogPosting"}:
        return ContentType.article
    if "FAQPage" in t:
        return ContentType.faq
    return ContentType.generic


# --- per-type completeness checks -------------------------------------------

def primary_product(h: Harvest) -> dict:
    """The main product entity, not a bare {@type, url} variant stub.

    Real PDPs carry a rich ProductGroup plus many minimal Product stubs (related
    items, breadcrumbs). Prefer a *named* entity, ProductGroup first.
    """
    candidates = h.all_of_type("ProductGroup") + h.all_of_type("Product")
    for cand in candidates:
        if cand.get("name"):
            return cand
    return candidates[0]


def _product_complete(h: Harvest):
    p = primary_product(h)
    name = p.get("name")
    price = deep_find(p, {"price", "lowPrice"})
    avail = deep_find(p, {"availability"})
    has_desc = bool(p.get("description"))
    n_attrs = sum(1 for k in _PRODUCT_ATTRS if p.get(k) not in (None, "", []))
    if name and price and avail and (has_desc or n_attrs >= 3):
        return True, "product: name+price+availability+(description or >=3 attrs)"
    missing = [n for n, v in (("name", name), ("price", price), ("availability", avail)) if not v]
    if not (has_desc or n_attrs >= 3):
        missing.append("description/attrs")
    return False, f"product missing: {', '.join(missing)}"


def _article_complete(h: Harvest):
    a = (h.first_of_type("NewsArticle") or h.first_of_type("Article")
         or h.first_of_type("BlogPosting"))
    headline = a.get("headline") or a.get("name")
    byline = a.get("author") or a.get("publisher")
    date = a.get("datePublished")
    if headline and byline and date:
        return True, "article: headline+author/publisher+datePublished"
    missing = [n for n, v in (("headline", headline), ("author/publisher", byline),
                              ("datePublished", date)) if not v]
    return False, f"article missing: {', '.join(missing)}"


def _faq_complete(h: Harvest):
    q = h.first_of_type("Question")
    if q and deep_find(q, {"acceptedAnswer"}):
        return True, "faq: question with acceptedAnswer"
    return False, "faq missing question/acceptedAnswer"


def _listing_complete(h: Harvest):
    il = h.first_of_type("ItemList")
    if il is None:
        return False, "listing has no ItemList -> escalate"
    items = il.get("itemListElement") or []
    if not isinstance(items, list):
        items = [items]
    good = [it for it in items
            if deep_find(it, {"name"}) and deep_find(it, {"url"})]
    if len(good) >= MIN_LIST_ITEMS:
        return True, f"itemlist with {len(good)} named+linked items"
    return False, f"itemlist has {len(good)} usable items (< {MIN_LIST_ITEMS})"
