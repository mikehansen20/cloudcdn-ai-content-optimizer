"""ModelClient stub tests verifying offline stand-in output derivation."""

import unittest

from cascade.model import ModelOutput, StubModelClient
from cascade.schema import ContentType


class Stub(unittest.TestCase):
    def setUp(self):
        self.client = StubModelClient()

    def test_uses_grounding_title_when_present(self):
        out = self.client.extract(
            dom_text="Lots of body text here.",
            grounding={"title": "Grounded Title"},
            content_type=ContentType.generic,
        )
        self.assertIsInstance(out, ModelOutput)
        self.assertEqual(out.title, "Grounded Title")

    def test_falls_back_to_first_line_of_dom_text(self):
        out = self.client.extract(
            dom_text="\n  First Line\nsecond line\n",
            grounding={},
            content_type=ContentType.generic,
        )
        self.assertEqual(out.title, "First Line")

    def test_body_is_the_provided_dom_text(self):
        out = self.client.extract(
            dom_text="the body", grounding={"title": "T"}, content_type=ContentType.generic
        )
        self.assertEqual(out.body_markdown, "the body")

    def test_echoes_grounded_facts_without_inventing(self):
        out = self.client.extract(
            dom_text="body",
            grounding={"title": "T", "facts": {"price": "110.00"}},
            content_type=ContentType.product,
        )
        self.assertEqual(out.type_fields, {"price": "110.00"})


if __name__ == "__main__":
    unittest.main()
