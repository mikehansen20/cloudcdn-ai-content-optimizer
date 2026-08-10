"""Cascade orchestrator acceptance tests executing end to end."""

import unittest
from datetime import datetime, timezone

from cascade.cascade import run_cascade
from cascade.model import ModelOutput, StubModelClient
from cascade.schema import ContentType, ExtractionPath

NOW = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)


def _ldjson(body):
    return f'<html><body><script type="application/ld+json">{body}</script></body></html>'


PRODUCT = _ldjson("""
{"@type":"Product","name":"Sample Sneaker","description":"A comfortable shoe.",
 "sku":"SS-1","brand":{"@type":"Brand","name":"Acme"},
 "offers":{"@type":"Offer","price":"110.00","priceCurrency":"USD",
           "availability":"https://schema.org/InStock"}}""")

ARTICLE = _ldjson("""
{"@type":"NewsArticle","headline":"Big News Today","description":"A summary.",
 "author":{"@type":"Person","name":"A. Writer"},"datePublished":"2026-06-30",
 "articleBody":"The full story body."}""")


class DeterministicProduct(unittest.TestCase):
    def test_pdp_takes_deterministic_path_with_correct_facts(self):
        r = run_cascade(PRODUCT, url="https://example.test/p",
                        model_client=StubModelClient(), now=NOW)
        fm = r.front_matter
        self.assertEqual(fm.content_type, ContentType.product)
        self.assertEqual(fm.extraction_path, ExtractionPath.deterministic)
        self.assertIsNone(fm.model)  # provenance: no model used
        self.assertEqual(fm.title, "Sample Sneaker")
        self.assertEqual(fm.type_fields.get("price"), "110.00")
        self.assertEqual(fm.type_fields.get("availability"), "InStock")
        self.assertIn("# Sample Sneaker", r.markdown)
        self.assertIn("110.00", r.markdown)

    def test_pdp_hybrid_mode_includes_structured_facts_at_top_and_rich_body(self):
        html = f"""
        <html>
        <head><script type="application/ld+json">
        {{"@type":"Product","name":"Pro Running Shoe","description":"Elite runner.",
          "sku":"PRS-99","brand":{{"@type":"Brand","name":"Fleet"}},
          "offers":{{"@type":"Offer","price":"149.99","priceCurrency":"USD","availability":"https://schema.org/InStock"}}}}
        </script></head>
        <body>
            <main>
                <h2>Product Overview</h2>
                <p>Engineered for marathon training with responsive foam cushioning.</p>
                <h3>Specifications</h3>
                <ul>
                    <li>Drop: 8mm</li>
                    <li>Weight: 240g</li>
                </ul>
            </main>
        </body>
        </html>
        """
        r = run_cascade(html, url="https://example.test/shoe",
                        model_client=StubModelClient(), now=NOW)
        self.assertEqual(r.front_matter.extraction_path, ExtractionPath.deterministic)
        self.assertIsNone(r.front_matter.model)  # 0 LLM calls
        md = r.markdown
        # 1. Title and URL at the top
        self.assertTrue(md.startswith("# Pro Running Shoe\n\n**URL:** https://example.test/shoe"))
        # 2. Structured facts at the top
        self.assertIn("- **Price:** 149.99 USD", md)
        self.assertIn("- **Availability:** InStock", md)
        self.assertIn("- **SKU:** PRS-99", md)
        self.assertIn("- **Brand:** Fleet", md)
        # 3. Rich page content appended below
        self.assertIn("## Product Overview", md)
        self.assertIn("Engineered for marathon training with responsive foam cushioning.", md)
        self.assertIn("### Specifications", md)
        self.assertIn("- Drop: 8mm", md)
        self.assertIn("- Weight: 240g", md)


class DeterministicArticle(unittest.TestCase):
    def test_article_takes_deterministic_path(self):
        r = run_cascade(ARTICLE, url="https://example.test/a",
                        model_client=StubModelClient(), now=NOW)
        self.assertEqual(r.front_matter.content_type, ContentType.article)
        self.assertEqual(r.front_matter.extraction_path, ExtractionPath.deterministic)
        self.assertEqual(r.front_matter.title, "Big News Today")
        self.assertIn("The full story body.", r.markdown)

    def test_article_hybrid_mode_extracts_html_body(self):
        html = """
        <html>
        <head><script type="application/ld+json">
        {"@type":"NewsArticle","headline":"Quarterly Report Released","description":"Financial summary.",
         "author":{"@type":"Person","name":"Jane Doe"},"datePublished":"2026-08-01"}
        </script></head>
        <body>
            <article>
                <p>Company revenue increased by 25% year-over-year in the second quarter.</p>
                <h2>Key Drivers</h2>
                <p>Growth was driven by international expansion and cloud adoption.</p>
            </article>
        </body>
        </html>
        """
        r = run_cascade(html, url="https://example.test/report",
                        model_client=StubModelClient(), now=NOW)
        self.assertEqual(r.front_matter.extraction_path, ExtractionPath.deterministic)
        md = r.markdown
        self.assertIn("- **Author:** Jane Doe", md)
        self.assertIn("- **Published:** 2026-08-01", md)
        self.assertIn("Company revenue increased by 25% year-over-year", md)
        self.assertIn("## Key Drivers", md)


class GenericEscalates(unittest.TestCase):
    def test_structured_data_poor_page_uses_the_model_path(self):
        html = "<html><body><h1>Welcome</h1><p>Marketing prose here.</p></body></html>"
        r = run_cascade(html, url="https://example.test/g",
                        model_client=StubModelClient(), now=NOW)
        fm = r.front_matter
        self.assertEqual(fm.content_type, ContentType.generic)
        self.assertEqual(fm.extraction_path, ExtractionPath.model)
        self.assertEqual(fm.model, "stub")  # provenance records the model
        self.assertIn("Marketing prose here.", r.markdown)

    def test_empty_model_body_falls_back_to_html_content(self):
        class TitleOnlyModel:
            model_id = "title_only"
            def extract(self, *, dom_text, grounding, content_type):
                # Returns only title or empty body_markdown
                return ModelOutput(title="Synthetic Product #14", body_markdown="# Synthetic Product #14\n")

        html = """
        <html>
        <body>
            <h1>Synthetic Product #14</h1>
            <h2>Product Overview</h2>
            <p>Welcome to product 14 details.</p>
        </body>
        </html>
        """
        r = run_cascade(html, url="https://example.test/p14",
                        model_client=TitleOnlyModel(), now=NOW)
        self.assertEqual(r.front_matter.extraction_path, ExtractionPath.model)
        self.assertIn("## Product Overview", r.markdown)
        self.assertIn("Welcome to product 14 details.", r.markdown)


class LargePageTruncation(unittest.TestCase):
    def test_dom_text_is_capped_before_the_model(self):
        seen = {}

        class CapturingModel:
            model_id = "cap"
            def extract(self, *, dom_text, grounding, content_type):
                seen["len"] = len(dom_text)
                return ModelOutput(title="T", body_markdown=dom_text)

        big = "<html><body><p>" + ("word " * 5000) + "</p></body></html>"
        run_cascade(big, url="https://e.test/big", model_client=CapturingModel(),
                    now=NOW, max_model_chars=100)
        self.assertLessEqual(seen["len"], 100)


class ValidationDropsHallucinations(unittest.TestCase):
    def test_model_fact_absent_from_source_is_dropped(self):
        # a model that invents a fact not present in the page
        class InventingModel:
            model_id = "fake"
            def extract(self, *, dom_text, grounding, content_type):
                return ModelOutput(title="Welcome", body_markdown=dom_text,
                                   type_fields={"price": "999.99"})  # not on the page

        html = "<html><body><h1>Welcome</h1><p>No prices here at all.</p></body></html>"
        r = run_cascade(html, url="https://example.test/g", model_client=InventingModel(), now=NOW)
        self.assertNotIn("price", r.front_matter.type_fields)  # dropped by the validation gate


if __name__ == "__main__":
    unittest.main()
