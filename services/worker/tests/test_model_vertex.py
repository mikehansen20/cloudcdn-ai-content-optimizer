"""Vertex client offline tests covering prompt construction and response parsing."""

import unittest

from cascade.model import ModelClient, ModelOutput
from cascade.model_vertex import (
    VertexModelClient,
    build_extraction_request,
    call_with_retry,
    parse_model_output,
)
from cascade.schema import ContentType


class PromptConstruction(unittest.TestCase):
    def setUp(self):
        self.system, self.user = build_extraction_request(
            dom_text="Hello world body.",
            grounding={"title": "Grounded T", "facts": {"price": "110.00"}},
            content_type=ContentType.product,
        )

    def test_system_defends_against_prompt_injection(self):
        self.assertIn("untrusted", self.system.lower())
        self.assertIn("never", self.system.lower())

    def test_system_names_the_content_type(self):
        self.assertIn("product", self.system.lower())

    def test_user_carries_grounding_facts_and_page_data(self):
        self.assertIn("110.00", self.user)        # grounded fact
        self.assertIn("Grounded T", self.user)     # grounded title
        self.assertIn("Hello world body.", self.user)  # page text

    def test_page_content_is_delimited(self):
        # the untrusted page must be fenced so it can't be confused with instructions
        self.assertIn("PAGE", self.user)
        self.assertGreater(self.user.index("Hello world body."), self.user.index("PAGE"))


class ResponseParsing(unittest.TestCase):
    def test_parses_plain_json(self):
        out = parse_model_output('{"title":"T","body_markdown":"B","type_fields":{"price":"5"}}')
        self.assertIsInstance(out, ModelOutput)
        self.assertEqual(out.title, "T")
        self.assertEqual(out.type_fields["price"], "5")

    def test_parses_fenced_json(self):
        out = parse_model_output('```json\n{"title":"T","body_markdown":"B"}\n```')
        self.assertEqual(out.title, "T")


class Interface(unittest.TestCase):
    def test_is_a_model_client_with_a_model_id(self):
        client = VertexModelClient(project="test-project")
        self.assertIsInstance(client, ModelClient)
        self.assertEqual(client.model_id, "gemini-3.5-flash")

class RetryLogic(unittest.TestCase):
    def test_succeeds_without_retrying(self):
        calls = []

        def target():
            calls.append(1)
            return "ok"

        res = call_with_retry(target, max_attempts=3, initial_delay=0.01)
        self.assertEqual(res, "ok")
        self.assertEqual(len(calls), 1)

    def test_retries_on_429_and_succeeds(self):
        calls = []

        def target():
            calls.append(1)
            if len(calls) < 2:
                raise Exception("429 RESOURCE_EXHAUSTED: Rate limit exceeded")
            return "recovered"

        res = call_with_retry(target, max_attempts=3, initial_delay=0.01)
        self.assertEqual(res, "recovered")
        self.assertEqual(len(calls), 2)

    def test_does_not_retry_non_rate_limit_errors(self):
        calls = []

        def target():
            calls.append(1)
            raise ValueError("Invalid argument")

        with self.assertRaises(ValueError):
            call_with_retry(target, max_attempts=3, initial_delay=0.01)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
