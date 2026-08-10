"""Orchestration integration tests covering enumeration, processing, storage, and index building."""

import tempfile
import unittest

from cascade.cascade import run_cascade
from cascade.enumerator import enumerate_urls
from cascade.llms import LLMS_KEY, build_and_store
from cascade.model import StubModelClient
from aico_common.service_support import url_to_key
from aico_common.storage import LocalStorage

SITEMAP = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://demo.test/product</loc></url>
  <url><loc>https://demo.test/about</loc></url>
</urlset>"""

PRODUCT_HTML = (
    '<html><body><script type="application/ld+json">'
    '{"@type":"Product","name":"Demo Item","description":"A demo product.",'
    '"offers":{"@type":"Offer","price":"9.99","priceCurrency":"USD",'
    '"availability":"https://schema.org/InStock"}}'
    "</script></body></html>"
)
ABOUT_HTML = "<html><body><h1>About Us</h1><p>Marketing prose about the company.</p></body></html>"
PAGES = {"https://demo.test/product": PRODUCT_HTML, "https://demo.test/about": ABOUT_HTML}


class BatchOrchestration(unittest.TestCase):
    def test_enumerate_process_store_then_build_llms(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(tmp)

            # 1. enumerator fans the sitemap into per-URL work
            sitemap_fetch = lambda url, allowed_hosts=None: type("R", (), {"ok": True, "html": SITEMAP})()
            urls = list(enumerate_urls("https://demo.test/sitemap.xml", fetch=sitemap_fetch))
            self.assertEqual(urls, ["https://demo.test/product", "https://demo.test/about"])

            # 2. worker processes each URL (cascade -> storage), persisting the full
            #    provenance as object metadata exactly as the worker does.
            for url in urls:
                result = run_cascade(PAGES[url], url, model_client=StubModelClient())
                storage.write(url_to_key(url), result.markdown,
                              result.front_matter.to_metadata_dict())

            self.assertTrue(storage.exists("/product.md"))
            self.assertEqual(storage.get_metadata("/product.md")["content_type"], "product")
            self.assertTrue(storage.exists("/about.md"))
            # the stored page carries no front matter; provenance is in object metadata
            product_md = storage.read("/product.md")
            self.assertFalse(product_md.startswith("---"))
            self.assertNotIn("source_hash", product_md)
            self.assertIn("**URL:** https://demo.test/product", product_md)

            # 3. Index build sourcing flat list from object metadata
            build_and_store(storage, site_title="Demo")
            llms = storage.read(LLMS_KEY)
            self.assertNotIn("##", llms)  # no content_type grouping
            self.assertIn("- [Demo Item](https://demo.test/product): A demo product.", llms)
            self.assertIn("(https://demo.test/about)", llms)  # the about page is indexed too


if __name__ == "__main__":
    unittest.main()
