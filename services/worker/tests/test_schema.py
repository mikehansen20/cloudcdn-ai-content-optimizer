"""Front-matter schema tests verifying output contracts and validation rules."""

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from cascade.schema import ContentType, ExtractionPath, FrontMatter


def _base(**overrides):
    data = dict(
        url="https://example.test/page",
        title="A Page",
        content_type=ContentType.generic,
        source_hash="abc123",
        generated_at=datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc),
        extraction_path=ExtractionPath.model,
        model="gemini-3.5-flash",
    )
    data.update(overrides)
    return data


class CoreContract(unittest.TestCase):
    def test_builds_a_valid_model_path_front_matter(self):
        fm = FrontMatter(**_base())
        self.assertEqual(fm.content_type, ContentType.generic)
        self.assertEqual(fm.extraction_path, ExtractionPath.model)
        self.assertEqual(fm.schema_version, 1)  # defaulted

    def test_deterministic_path_needs_no_model(self):
        fm = FrontMatter(**_base(extraction_path=ExtractionPath.deterministic, model=None))
        self.assertIsNone(fm.model)

    def test_model_path_requires_a_model_id(self):
        with self.assertRaises(ValidationError):
            FrontMatter(**_base(extraction_path=ExtractionPath.model, model=None))

    def test_deterministic_path_rejects_a_model_id(self):
        # provenance must be honest: a deterministic page did not use a model
        with self.assertRaises(ValidationError):
            FrontMatter(**_base(extraction_path=ExtractionPath.deterministic, model="gemini-3.5-flash"))

    def test_rejects_unknown_content_type(self):
        with self.assertRaises(ValidationError):
            FrontMatter(**_base(content_type="podcast"))

    def test_missing_required_core_field_is_rejected(self):
        data = _base()
        del data["source_hash"]
        with self.assertRaises(ValidationError):
            FrontMatter(**data)


class TypeSpecificBlock(unittest.TestCase):
    def test_accepts_open_type_specific_fields(self):
        fm = FrontMatter(**_base(
            content_type=ContentType.product,
            extraction_path=ExtractionPath.deterministic,
            model=None,
            type_fields={"price": "110.00", "currency": "USD", "availability": "InStock"},
        ))
        self.assertEqual(fm.type_fields["price"], "110.00")

    def test_generic_page_with_no_type_fields_is_valid(self):
        fm = FrontMatter(**_base())
        self.assertEqual(fm.type_fields, {})


class MetadataDict(unittest.TestCase):
    """to_metadata_dict() is the off-document provenance record (GCS object metadata).
    All values must be strings; null optionals are omitted; no type_fields."""

    def test_core_fields_are_all_strings(self):
        md = FrontMatter(**_base()).to_metadata_dict()
        self.assertTrue(all(isinstance(v, str) for v in md.values()))
        self.assertEqual(md["url"], "https://example.test/page")
        self.assertEqual(md["title"], "A Page")
        self.assertEqual(md["content_type"], "generic")
        self.assertEqual(md["source_hash"], "abc123")
        self.assertEqual(md["extraction_path"], "model")
        self.assertEqual(md["schema_version"], "1")
        self.assertEqual(md["generated_at"], "2026-06-30T12:00:00+00:00")
        self.assertEqual(md["model"], "gemini-3.5-flash")

    def test_omits_absent_optionals(self):
        md = FrontMatter(**_base(
            extraction_path=ExtractionPath.deterministic, model=None,
        )).to_metadata_dict()
        self.assertNotIn("model", md)
        self.assertNotIn("description", md)
        self.assertNotIn("source_validator", md)

    def test_includes_present_optionals_and_excludes_type_fields(self):
        md = FrontMatter(**_base(
            content_type=ContentType.product,
            extraction_path=ExtractionPath.deterministic, model=None,
            description="A blue widget.", source_validator="etag-1",
            type_fields={"price": "19.99"},
        )).to_metadata_dict()
        self.assertEqual(md["description"], "A blue widget.")
        self.assertEqual(md["source_validator"], "etag-1")
        self.assertNotIn("price", md)  # type_fields are not object metadata in v1


if __name__ == "__main__":
    unittest.main()
