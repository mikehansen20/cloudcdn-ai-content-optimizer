"""Completeness-gate tests covering decision table evaluation."""

import unittest

from cascade.gate import MIN_LIST_ITEMS, decide
from cascade.harvest import harvest_structured_data
from cascade.schema import ContentType, ExtractionPath


def gate_for(html: str):
    return decide(harvest_structured_data(html))


def _ldjson(body: str) -> str:
    return f'<script type="application/ld+json">{body}</script>'


PRODUCT_COMPLETE = _ldjson("""
{"@type":"Product","name":"Sample Sneaker","description":"A comfortable shoe.",
 "offers":{"@type":"Offer","price":"110.00","priceCurrency":"USD",
           "availability":"https://schema.org/InStock"}}""")


class ProductRow(unittest.TestCase):
    def test_complete_product_is_deterministic(self):
        d = gate_for(PRODUCT_COMPLETE)
        self.assertEqual(d.content_type, ContentType.product)
        self.assertEqual(d.path, ExtractionPath.deterministic)

    def test_product_missing_price_escalates(self):
        html = _ldjson("""{"@type":"Product","name":"X","description":"d",
            "offers":{"@type":"Offer","availability":"https://schema.org/InStock"}}""")
        d = gate_for(html)
        self.assertEqual(d.content_type, ContentType.product)
        self.assertEqual(d.path, ExtractionPath.model)

    def test_product_group_with_variant_offers_is_deterministic(self):
        html = _ldjson("""
        {"@type":"ProductGroup","name":"Sample Sneaker","description":"desc",
         "hasVariant":[{"@type":"Product","name":"Sample - Black",
            "offers":{"@type":"Offer","price":"110.00",
                      "availability":"https://schema.org/InStock"}}]}""")
        d = gate_for(html)
        self.assertEqual(d.content_type, ContentType.product)
        self.assertEqual(d.path, ExtractionPath.deterministic)


class ArticleRow(unittest.TestCase):
    def test_complete_article_is_deterministic(self):
        html = _ldjson("""{"@type":"NewsArticle","headline":"Big News",
            "author":{"@type":"Person","name":"A. Writer"},
            "datePublished":"2026-06-30"}""")
        d = gate_for(html)
        self.assertEqual(d.content_type, ContentType.article)
        self.assertEqual(d.path, ExtractionPath.deterministic)

    def test_article_missing_date_escalates(self):
        html = _ldjson("""{"@type":"Article","headline":"H",
            "author":{"@type":"Person","name":"A"}}""")
        d = gate_for(html)
        self.assertEqual(d.content_type, ContentType.article)
        self.assertEqual(d.path, ExtractionPath.model)


class FaqRow(unittest.TestCase):
    def test_faq_with_answered_question_is_deterministic(self):
        html = _ldjson("""{"@type":"FAQPage","mainEntity":[
            {"@type":"Question","name":"Q?","acceptedAnswer":{"@type":"Answer","text":"A."}}]}""")
        d = gate_for(html)
        self.assertEqual(d.content_type, ContentType.faq)
        self.assertEqual(d.path, ExtractionPath.deterministic)

    def test_faq_without_answer_escalates(self):
        html = _ldjson("""{"@type":"FAQPage","mainEntity":[
            {"@type":"Question","name":"Q?"}]}""")
        d = gate_for(html)
        self.assertEqual(d.content_type, ContentType.faq)
        self.assertEqual(d.path, ExtractionPath.model)


class ListingRow(unittest.TestCase):
    def test_itemlist_with_enough_named_linked_items_is_deterministic(self):
        items = ",".join(
            f'{{"@type":"ListItem","position":{i},"name":"Item {i}","url":"https://e.test/{i}"}}'
            for i in range(1, MIN_LIST_ITEMS + 1))
        html = _ldjson(f'{{"@type":"ItemList","itemListElement":[{items}]}}')
        d = gate_for(html)
        self.assertEqual(d.content_type, ContentType.listing)
        self.assertEqual(d.path, ExtractionPath.deterministic)

    def test_itemlist_too_small_escalates(self):
        html = _ldjson("""{"@type":"ItemList","itemListElement":[
            {"@type":"ListItem","position":1,"name":"Only","url":"https://e.test/1"}]}""")
        d = gate_for(html)
        self.assertEqual(d.content_type, ContentType.listing)
        self.assertEqual(d.path, ExtractionPath.model)


class GenericRow(unittest.TestCase):
    def test_no_structured_data_is_generic_and_always_escalates(self):
        d = gate_for("<html><body><p>Just prose.</p></body></html>")
        self.assertEqual(d.content_type, ContentType.generic)
        self.assertEqual(d.path, ExtractionPath.model)


class Precedence(unittest.TestCase):
    def test_product_takes_precedence_over_faq_on_the_same_page(self):
        html = PRODUCT_COMPLETE + _ldjson("""{"@type":"FAQPage","mainEntity":[
            {"@type":"Question","name":"Q?","acceptedAnswer":{"@type":"Answer","text":"A"}}]}""")
        d = gate_for(html)
        self.assertEqual(d.content_type, ContentType.product)


if __name__ == "__main__":
    unittest.main()
