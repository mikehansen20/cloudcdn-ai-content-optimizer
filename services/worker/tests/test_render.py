"""Render step tests covering content verification and cascade rendering integration."""

import unittest
from datetime import datetime, timezone

from cascade.cascade import run_cascade
from cascade.model import StubModelClient
from cascade.render import has_meaningful_content
from cascade.schema import ContentType

NOW = datetime(2026, 6, 30, tzinfo=timezone.utc)

JS_SHELL = '<html><body><div id="root"></div><script src="/static/app.js"></script></body></html>'
REAL_PAGE = "<html><body><h1>Title</h1>" + ("<p>Real words here. </p>" * 20) + "</body></html>"

RENDERED_HTML = (
    '<html><body><script type="application/ld+json">'
    '{"@type":"NewsArticle","headline":"Rendered Title",'
    '"author":{"@type":"Person","name":"A. Writer"},'
    '"datePublished":"2026-06-30","articleBody":"Body."}'
    "</script></body></html>"
)


class _SpyRenderer:
    def __init__(self, html):
        self.html = html
        self.called_with = None

    def render(self, url):
        self.called_with = url
        return self.html


class ContentPresentCheck(unittest.TestCase):
    def test_js_shell_has_no_meaningful_content(self):
        self.assertFalse(has_meaningful_content(JS_SHELL))

    def test_real_page_has_meaningful_content(self):
        self.assertTrue(has_meaningful_content(REAL_PAGE))


class RenderIntegration(unittest.TestCase):
    def test_renderer_invoked_on_shell_then_extracts_from_painted_dom(self):
        spy = _SpyRenderer(RENDERED_HTML)
        result = run_cascade(JS_SHELL, url="https://example.test/app",
                             model_client=StubModelClient(), renderer=spy, now=NOW)
        self.assertEqual(spy.called_with, "https://example.test/app")
        self.assertTrue(result.rendered)
        # content_type now comes from the painted DOM's structured data
        self.assertEqual(result.front_matter.content_type, ContentType.article)

    def test_renderer_not_invoked_when_content_is_present(self):
        spy = _SpyRenderer("<html></html>")
        result = run_cascade(REAL_PAGE, url="https://example.test/p",
                             model_client=StubModelClient(), renderer=spy, now=NOW)
        self.assertIsNone(spy.called_with)
        self.assertFalse(result.rendered)

    def test_no_renderer_means_no_render(self):
        result = run_cascade(JS_SHELL, url="https://example.test/app",
                             model_client=StubModelClient(), now=NOW)
        self.assertFalse(result.rendered)


if __name__ == "__main__":
    unittest.main()
