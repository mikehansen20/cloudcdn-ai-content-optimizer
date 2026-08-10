"""Validation-gate tests covering fact-category matching, field dropping, and degradation rules."""

import unittest

from cascade.validate import apply_validation, matches, validate_value


class NumericFacts(unittest.TestCase):
    def test_currency_and_decimal_normalize_equal(self):
        self.assertTrue(matches("$158.00", "158"))

    def test_percentage_normalizes(self):
        self.assertTrue(matches("3.50%", "3.5"))

    def test_thousands_separator_normalizes(self):
        self.assertTrue(matches("1,234.50", "1234.5"))

    def test_different_numbers_do_not_match(self):
        self.assertFalse(matches("158", "159"))

    def test_partial_number_is_not_a_substring_match(self):
        # raw substring would wrongly pass "5" in "500"; numeric compare must not
        self.assertFalse(matches("5", "500"))


class EntityFacts(unittest.TestCase):
    def test_token_subset_matches_after_normalization(self):
        # model value is a token-subset of the DOM value (punctuation/diacritics ignored)
        self.assertTrue(matches("Sample Sneaker - Men's", "Sample Sneaker Men's Shoe"))

    def test_truncation_matches_via_reverse_subset(self):
        self.assertTrue(matches("Sample Sneaker Mens Shoe", "Sample Sneaker"))

    def test_unrelated_entities_do_not_match(self):
        self.assertFalse(matches("Completely Different", "Sample Sneaker"))

    def test_value_with_incidental_digits_is_treated_as_entity(self):
        # "Sample 90" is an entity, not a number; must not numeric-match a bare 90
        self.assertFalse(matches("Sample 90", "90"))


class ValidateAgainstCandidates(unittest.TestCase):
    def test_matches_any_candidate(self):
        self.assertTrue(validate_value("$158.00", ["out of stock", "158.0", "blue"]))

    def test_matches_no_candidate_is_false(self):
        self.assertFalse(validate_value("hallucinated", ["158", "blue", "Sample Sneaker"]))


class PageLevelDropAndDegrade(unittest.TestCase):
    def test_keeps_validated_drops_unmatched(self):
        result = apply_validation(
            facts={"price": "$158.00", "sku": "ABC-123", "ghost": "made up"},
            candidates=["158", "ABC-123", "Sample Sneaker"],
            required={"price"},
        )
        self.assertIn("price", result.kept)
        self.assertIn("sku", result.kept)
        self.assertIn("ghost", result.dropped)
        self.assertFalse(result.degrade)  # only an optional field was dropped

    def test_required_field_no_match_triggers_degrade(self):
        result = apply_validation(
            facts={"title": "Totally Wrong Title"},
            candidates=["Sample Sneaker", "158"],
            required={"title"},
        )
        self.assertIn("title", result.dropped)
        self.assertTrue(result.degrade)


if __name__ == "__main__":
    unittest.main()
