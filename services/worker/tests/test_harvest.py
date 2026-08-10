"""Harvester unit tests using small synthetic HTML input."""

import unittest

from cascade.harvest import harvest_structured_data


class HarvestJsonLd(unittest.TestCase):
    def test_extracts_product_object_from_json_ld(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {"@context": "https://schema.org", "@type": "Product",
           "name": "Sample Sneaker",
           "offers": {"@type": "Offer", "price": "110.00",
                      "priceCurrency": "USD",
                      "availability": "https://schema.org/InStock"}}
          </script>
        </head><body></body></html>
        """
        harvest = harvest_structured_data(html)
        product = harvest.first_of_type("Product")
        self.assertIsNotNone(product)
        self.assertEqual(product["name"], "Sample Sneaker")

    def test_flattens_graph_container_into_individual_objects(self):
        html = """
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@graph": [
           {"@type": "WebSite", "name": "Example"},
           {"@type": "Article", "headline": "Hello"}]}
        </script>
        """
        harvest = harvest_structured_data(html)
        self.assertEqual(harvest.types, {"WebSite", "Article"})

    def test_skips_a_malformed_block_but_keeps_valid_ones(self):
        html = """
        <script type="application/ld+json">{ not valid json }</script>
        <script type="application/ld+json">{"@type": "Thing", "name": "ok"}</script>
        """
        harvest = harvest_structured_data(html)
        self.assertEqual(harvest.types, {"Thing"})

    def test_handles_type_given_as_a_list(self):
        html = """
        <script type="application/ld+json">
        {"@type": ["Product", "IndividualProduct"], "name": "Combo"}
        </script>
        """
        harvest = harvest_structured_data(html)
        self.assertIsNotNone(harvest.first_of_type("IndividualProduct"))
        self.assertIn("Product", harvest.types)

    def test_no_structured_data_yields_empty_harvest(self):
        harvest = harvest_structured_data("<html><body><p>plain</p></body></html>")
        self.assertEqual(harvest.json_ld, [])
        self.assertEqual(harvest.types, set())

    def test_finds_product_nested_in_a_product_group(self):
        # Real retail PDPs commonly use ProductGroup with Product variants nested
        # under hasVariant rather than a top-level Product.
        html = """
        <script type="application/ld+json">
        {"@type": "ProductGroup", "name": "Sample Sneaker",
         "hasVariant": [
            {"@type": "Product", "name": "Sample Sneaker - Black", "sku": "R-BLK"},
            {"@type": "Product", "name": "Sample Sneaker - Blue", "sku": "R-BLU"}]}
        </script>
        """
        harvest = harvest_structured_data(html)
        self.assertIsNotNone(harvest.first_of_type("ProductGroup"))
        self.assertIsNotNone(harvest.first_of_type("Product"))
        self.assertIn("Product", harvest.types)

    def test_finds_itemlist_nested_in_a_collection_page(self):
        # Real listing pages commonly nest ItemList under CollectionPage.mainEntity.
        html = """
        <script type="application/ld+json">
        {"@type": "CollectionPage", "name": "Shoes",
         "mainEntity": {"@type": "ItemList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "url": "https://example.test/1"}]}}
        </script>
        """
        harvest = harvest_structured_data(html)
        self.assertIsNotNone(harvest.first_of_type("ItemList"))


if __name__ == "__main__":
    unittest.main()
