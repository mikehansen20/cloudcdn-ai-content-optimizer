"""Unit tests for HTML to Markdown body extractor."""

import unittest

from cascade.html_markdown import extract_body_markdown


class TestExtractBodyMarkdown(unittest.TestCase):
    def test_converts_headings_and_paragraphs(self):
        html = """
        <html>
        <body>
            <h1>Main Title</h1>
            <p>First paragraph with <strong>bold</strong> and <em>italic</em> text.</p>
            <h2>Features</h2>
            <p>Second paragraph.</p>
        </body>
        </html>
        """
        md = extract_body_markdown(html, exclude_headings={"Main Title"})
        self.assertNotIn("# Main Title", md)
        self.assertIn("First paragraph with **bold** and *italic* text.", md)
        self.assertIn("## Features", md)
        self.assertIn("Second paragraph.", md)

    def test_converts_unordered_and_ordered_lists(self):
        html = """
        <html>
        <body>
            <h3>Specifications</h3>
            <ul>
                <li>Durable composite</li>
                <li>Energy efficient</li>
            </ul>
            <ol>
                <li>Step one</li>
                <li>Step two</li>
            </ol>
        </body>
        </html>
        """
        md = extract_body_markdown(html)
        self.assertIn("### Specifications", md)
        self.assertIn("- Durable composite", md)
        self.assertIn("- Energy efficient", md)
        self.assertIn("1. Step one", md)
        self.assertIn("2. Step two", md)

    def test_converts_html_tables(self):
        html = """
        <html>
        <body>
            <table>
                <thead>
                    <tr><th>Spec</th><th>Value</th></tr>
                </thead>
                <tbody>
                    <tr><td>Weight</td><td>1.2 kg</td></tr>
                    <tr><td>Dimensions</td><td>10x15x20 cm</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """
        md = extract_body_markdown(html)
        self.assertIn("| Spec | Value |", md)
        self.assertIn("|---|---|", md)
        self.assertIn("| Weight | 1.2 kg |", md)
        self.assertIn("| Dimensions | 10x15x20 cm |", md)

    def test_strips_scripts_styles_nav_and_footer(self):
        html = """
        <html>
        <head>
            <style>body { color: red; }</style>
            <script>console.log("ad code");</script>
        </head>
        <body>
            <header><nav><a href="/home">Home</a></nav></header>
            <main>
                <h2>Product Overview</h2>
                <p>Real product information here.</p>
            </main>
            <footer><p>Copyright 2026</p></footer>
        </body>
        </html>
        """
        md = extract_body_markdown(html)
        self.assertNotIn("console.log", md)
        self.assertNotIn("Copyright 2026", md)
        self.assertNotIn("Home", md)
        self.assertIn("## Product Overview", md)
        self.assertIn("Real product information here.", md)

    def test_converts_links_and_code(self):
        html = """
        <html>
        <body>
            <p>Visit <a href="https://example.com/docs">the documentation</a> for details.</p>
            <pre><code>pip install aico</code></pre>
            <p>Inline <code>code</code> sample.</p>
        </body>
        </html>
        """
        md = extract_body_markdown(html)
        self.assertIn("[the documentation](https://example.com/docs)", md)
        self.assertIn("```\npip install aico\n```", md)
        self.assertIn("Inline `code` sample.", md)

    def test_strips_hidden_elements(self):
        html = """
        <html>
        <body>
            <p>Visible text.</p>
            <p style="display:none">Hidden text.</p>
            <div hidden>Also hidden.</div>
            <div aria-hidden="true">Screen reader hidden.</div>
        </body>
        </html>
        """
        md = extract_body_markdown(html)
        self.assertIn("Visible text.", md)
        self.assertNotIn("Hidden text.", md)
        self.assertNotIn("Also hidden.", md)
        self.assertNotIn("Screen reader hidden.", md)


if __name__ == "__main__":
    unittest.main()
