"""Tests for the ordered selector registry and its resolver."""

import unittest

from bs4 import BeautifulSoup

from src.idealista.selectors import ResolvedField, resolve_field

HTML = """
<article>
  <span class="item-price">598.000</span>
  <span class="legacy-price-fallback">515.000</span>
</article>
"""


class TestResolveField(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = BeautifulSoup(HTML, "html.parser")

    def test_returns_the_text_and_selector_of_the_first_match(self) -> None:
        result = resolve_field(self.tree, ["span.item-price", "span.legacy-price-fallback"])
        self.assertEqual(result, ResolvedField("598.000", "span.item-price"))

    def test_falls_back_to_the_next_selector_when_the_first_does_not_match(self) -> None:
        result = resolve_field(self.tree, ["span.renamed-price-class", "span.legacy-price-fallback"])
        self.assertEqual(result, ResolvedField("515.000", "span.legacy-price-fallback"))

    def test_returns_none_none_when_no_selector_matches(self) -> None:
        result = resolve_field(self.tree, ["span.does-not-exist", "span.also-missing"])
        self.assertEqual(result, ResolvedField(None, None))

    def test_an_empty_selector_list_returns_none_none(self) -> None:
        self.assertEqual(resolve_field(self.tree, []), ResolvedField(None, None))

    def test_adding_a_fallback_is_a_data_change_not_a_code_change(self) -> None:
        # The registry is plain data: a caller builds its own field -> selector-list mapping and
        # extends it by appending a string, without touching resolve_field itself.
        registry: dict[str, list[str]] = {
            "price_eur": ["span.renamed-price-class"],
        }
        text, matched = resolve_field(self.tree, registry["price_eur"])
        self.assertIsNone(text)

        registry["price_eur"].append("span.legacy-price-fallback")
        text, matched = resolve_field(self.tree, registry["price_eur"])
        self.assertEqual((text, matched), ("515.000", "span.legacy-price-fallback"))


if __name__ == "__main__":
    unittest.main()
