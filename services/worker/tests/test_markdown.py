"""Markdown renderer tests verifying canonical title and URL formatting without front matter.

Output document contains the canonical title and URL line followed by body content.
"""

import unittest
from datetime import datetime, timezone

from cascade.markdown import render_markdown
from cascade.schema import ContentType, ExtractionPath, FrontMatter


def _fm(title="Example Domain"):
    return FrontMatter(
        url="https://example.test/p",
        title=title,
        content_type=ContentType.generic,
        source_hash="h",
        generated_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        extraction_path=ExtractionPath.model,
        model="gemini-3.5-flash",
    )


class RenderMarkdown(unittest.TestCase):
    def test_has_no_front_matter_or_provenance(self):
        out = render_markdown(_fm(), "Some prose.")
        self.assertFalse(out.startswith("---"))
        for leaked in ("content_type", "source_hash", "extraction_path", "generated_at"):
            self.assertNotIn(leaked, out)

    def test_headingless_body_gets_canonical_title(self):
        # model path: body is prose with no leading '#'
        out = render_markdown(_fm(), "This domain is for examples.\n\nLearn more")
        self.assertTrue(out.startswith("# Example Domain\n"))
        self.assertIn("**URL:** https://example.test/p", out)
        self.assertLess(out.index("# Example Domain"), out.index("**URL:**"))
        self.assertLess(out.index("**URL:**"), out.index("This domain"))

    def test_body_with_own_h1_is_not_duplicated(self):
        # deterministic path: body already leads with '# Title'
        out = render_markdown(_fm("Blue Widget"), "# Blue Widget\n\n- **Price:** 19.99")
        self.assertEqual(out.count("# Blue Widget"), 1)
        self.assertTrue(out.startswith("# Blue Widget\n"))
        self.assertIn("**URL:** https://example.test/p", out)
        self.assertIn("- **Price:** 19.99", out)

    def test_body_is_newline_terminated(self):
        out = render_markdown(_fm(), "body")
        self.assertTrue(out.endswith("body\n"))


if __name__ == "__main__":
    unittest.main()
