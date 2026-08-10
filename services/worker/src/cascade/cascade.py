"""Cascade orchestrator executing HTML processing pipeline to Markdown.

Deterministic path: structured data is formatted directly without model execution.
Escalate path: model reformats and extracts page text using harvested facts as grounding context.
Model-emitted facts are validated against source data; required field failures fall back to deterministic outputs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from cascade.gate import GateDecision, decide, primary_product
from cascade.harvest import Harvest, deep_find, harvest_structured_data
from cascade.html_markdown import extract_body_markdown
from cascade.markdown import render_markdown
from cascade.model import ModelClient
from cascade.render import Renderer, has_meaningful_content
from cascade.schema import ContentType, ExtractionPath, FrontMatter
from cascade.textutil import extract_text
from cascade.validate import apply_validation


# Cap on page text handed to the model. Very large pages (e.g. a 1.4 MB page)
# are slow and can exceed context; the extracted text is truncated to this many
# characters before the model call.
MAX_MODEL_CHARS = 200_000


@dataclass
class CascadeResult:
    markdown: str
    front_matter: FrontMatter
    decision: GateDecision
    degraded: bool
    rendered: bool = False


def run_cascade(
    html: str,
    url: str,
    *,
    model_client: ModelClient,
    renderer: Renderer | None = None,
    now: datetime | None = None,
    source_hash: str | None = None,
    source_validator: str | None = None,
    max_model_chars: int = MAX_MODEL_CHARS,
) -> CascadeResult:
    now = now or datetime.now(timezone.utc)
    if source_hash is None:
        # Hash the fetched HTML for change detection before rendering.
        source_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()

    harvest = harvest_structured_data(html)
    rendered = False
    if renderer is not None and not has_meaningful_content(html):
        # JS shell -> render to the painted DOM, then harvest/extract against that.
        html = renderer.render(url)
        harvest = harvest_structured_data(html)
        rendered = True
    decision = decide(harvest)

    if decision.path is ExtractionPath.deterministic:
        title, description, type_fields, body = _format_deterministic(decision.content_type, harvest, html)
        fm = _front_matter(url, title, decision.content_type, description, source_hash,
                           source_validator, now, ExtractionPath.deterministic, None, type_fields)
        result = CascadeResult(render_markdown(fm, body), fm, decision, degraded=False)
    else:
        result = _escalate(decision, harvest, html, url, now, source_hash,
                           source_validator, model_client, max_model_chars)
    result.rendered = rendered
    return result


# --- escalate path ----------------------------------------------------------

def _escalate(decision, harvest, html, url, now, source_hash, validator, client,
              max_model_chars=MAX_MODEL_CHARS) -> CascadeResult:
    dom_text = extract_text(html)[:max_model_chars]  # cap large pages before the model
    grounding = _grounding(harvest)
    output = client.extract(dom_text=dom_text, grounding=grounding, content_type=decision.content_type)

    # Validate model-emitted discrete facts against authoritative source values.
    candidates = _source_candidates(harvest)
    result = apply_validation(output.type_fields, candidates, required=())
    if result.degrade:
        # Required fact failed validation -> safe degraded result (deterministic fallback).
        title, description, type_fields, body = _format_deterministic(decision.content_type, harvest, html)
        fm = _front_matter(url, title, decision.content_type, description, source_hash,
                           validator, now, ExtractionPath.deterministic, None, type_fields)
        return CascadeResult(render_markdown(fm, body), fm, decision, degraded=True)

    body_md = (output.body_markdown or "").strip()
    if body_md.startswith("# "):
        _, _, rest = body_md.partition("\n")
        rest = rest.strip()
    else:
        rest = body_md
    if not rest and html:
        body_md = extract_body_markdown(html, exclude_headings={output.title})

    fm = _front_matter(url, output.title, decision.content_type, output.description, source_hash,
                       validator, now, ExtractionPath.model, client.model_id, result.kept)
    return CascadeResult(render_markdown(fm, body_md), fm, decision, degraded=False)


# --- deterministic formatters (hybrid Schema.org + HTML body) ---------------

def _format_deterministic(content_type: ContentType, h: Harvest, html: str = ""):
    if content_type is ContentType.product:
        return _product(h, html)
    if content_type is ContentType.article:
        return _article(h, html)
    if content_type is ContentType.faq:
        return _faq(h, html)
    if content_type is ContentType.listing:
        return _listing(h, html)
    # generic never reaches deterministic, but stay safe
    title = _name_of(h.first_of_type("WebPage")) or "Page"
    body_md = extract_body_markdown(html, exclude_headings={title}) if html else ""
    body = f"# {title}\n\n{body_md}".strip() if body_md else f"# {title}\n"
    return title, None, {}, body


def _product(h: Harvest, html: str = ""):
    p = primary_product(h)
    name = p.get("name") or "Product"
    description = p.get("description")
    price = deep_find(p, {"price", "lowPrice"})
    currency = deep_find(p, {"priceCurrency"})
    availability = _short(deep_find(p, {"availability"}))
    sku = p.get("sku")
    brand = _name_of(p.get("brand"))

    type_fields: dict[str, str] = {}
    if price is not None:
        type_fields["price"] = str(price)
    if currency:
        type_fields["currency"] = str(currency)
    if availability:
        type_fields["availability"] = availability
    if sku:
        type_fields["sku"] = str(sku)
    if brand:
        type_fields["brand"] = brand

    lines = [f"# {name}", ""]
    if description:
        lines += [str(description), ""]
    facts = []
    if price is not None:
        facts.append(f"- **Price:** {price}" + (f" {currency}" if currency else ""))
    if availability:
        facts.append(f"- **Availability:** {availability}")
    if sku:
        facts.append(f"- **SKU:** {sku}")
    if brand:
        facts.append(f"- **Brand:** {brand}")
    lines += facts

    if html:
        body_md = extract_body_markdown(html, exclude_headings={name})
        if body_md:
            lines += ["", body_md]

    return name, _as_str(description), type_fields, "\n".join(lines).strip()


def _article(h: Harvest, html: str = ""):
    a = (h.first_of_type("NewsArticle") or h.first_of_type("Article")
         or h.first_of_type("BlogPosting"))
    title = a.get("headline") or a.get("name") or "Article"
    description = _as_str(a.get("description"))
    author = _name_of(a.get("author"))
    published = a.get("datePublished")
    section = a.get("articleSection")
    body_text = (a.get("articleBody") or "").strip()

    type_fields: dict[str, str] = {}
    if author:
        type_fields["author"] = author
    if published:
        type_fields["published_at"] = str(published)
    if section:
        type_fields["section"] = str(section)

    lines = [f"# {title}", ""]
    facts = []
    if author:
        facts.append(f"- **Author:** {author}")
    if published:
        facts.append(f"- **Published:** {published}")
    if section:
        facts.append(f"- **Section:** {section}")
    if facts:
        lines += facts + [""]

    if body_text:
        lines += [body_text]
    elif html:
        body_md = extract_body_markdown(html, exclude_headings={title})
        if body_md:
            lines += [body_md]

    return title, description, type_fields, "\n".join(lines).strip()


def _faq(h: Harvest, html: str = ""):
    pairs = []
    for q in h.all_of_type("Question"):
        question = q.get("name") or q.get("text")
        answer = deep_find(q, {"acceptedAnswer"})
        answer_text = deep_find(answer, {"text"}) if isinstance(answer, dict) else answer
        if question and answer_text:
            pairs.append((str(question), str(answer_text)))
    lines = ["# FAQ", ""]
    if pairs:
        lines += ["\n\n".join(f"## {q}\n\n{a}" for q, a in pairs)]
    if html and not pairs:
        body_md = extract_body_markdown(html, exclude_headings={"FAQ", "Frequently Asked Questions"})
        if body_md:
            lines += ["", body_md]
    body = "\n".join(lines).strip()
    return "FAQ", None, {}, body


def _listing(h: Harvest, html: str = ""):
    il = h.first_of_type("ItemList") or {}
    items = il.get("itemListElement") or []
    if not isinstance(items, list):
        items = [items]
    rows = []
    for it in items:
        name = deep_find(it, {"name"})
        link = deep_find(it, {"url"})
        if name and link:
            rows.append(f"- [{name}]({link})")
    title = il.get("name") or "Listing"
    lines = [f"# {title}", ""]
    if rows:
        lines += ["\n".join(rows)]
    if html and not rows:
        body_md = extract_body_markdown(html, exclude_headings={title})
        if body_md:
            lines += ["", body_md]
    body = "\n".join(lines).strip()
    return title, _as_str(il.get("description")), {}, body


# --- helpers ----------------------------------------------------------------

def _grounding(h: Harvest) -> dict:
    """Authoritative facts handed to the model as context (never invented)."""
    grounding: dict = {}
    for type_name, key in (("Product", "name"), ("ProductGroup", "name"),
                           ("NewsArticle", "headline"), ("Article", "headline")):
        entity = h.first_of_type(type_name)
        if entity and entity.get(key):
            grounding.setdefault("title", entity[key])
    return grounding


def _source_candidates(h: Harvest) -> list[str]:
    """Flatten harvested scalar leaf values into a match set."""
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, (str, int, float)):
            out.append(str(node))

    for obj in h.json_ld:
        walk(obj)
    return out


def _front_matter(url, title, content_type, description, source_hash, validator,
                  now, path, model_id, type_fields) -> FrontMatter:
    return FrontMatter(
        url=url,
        title=str(title),
        content_type=content_type,
        description=description,
        source_hash=source_hash,
        source_validator=validator,
        generated_at=now,
        extraction_path=path,
        model=model_id,
        type_fields=type_fields,
    )


def _short(availability) -> str | None:
    """`https://schema.org/InStock` -> `InStock`."""
    if not availability:
        return None
    return str(availability).rstrip("/").rsplit("/", 1)[-1]


def _name_of(value) -> str | None:
    """A schema.org value that may be a string or an object with a `name`."""
    if isinstance(value, dict):
        return value.get("name")
    if isinstance(value, list) and value:
        return _name_of(value[0])
    return value if isinstance(value, str) else None


def _as_str(value) -> str | None:
    return str(value) if value not in (None, "") else None
