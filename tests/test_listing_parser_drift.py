"""Drift behaviour of the detail parser: selector fallbacks, missing-field provenance and
rejection of records that lack a required field.
"""

import pathlib
import unittest
from datetime import datetime, timezone

from src.idealista.listing_parser import ListingRejected, parse_listing_html

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LISTING_URL = "https://www.idealista.com/inmueble/106749418/"
OBSERVED_AT = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

CONTEXT = dict(
    operation="sale",
    municipality="l-eliana",
    district=None,
    observed_at=OBSERVED_AT,
    extraction_version="1",
)


def _parse(fixture_name: str):
    html = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    return parse_listing_html(html, LISTING_URL, **CONTEXT)


class TestSelectorFallback(unittest.TestCase):
    def test_a_renamed_price_class_is_still_parsed_through_the_fallback(self) -> None:
        # Only the price class differs from idealista_listing.html: info-data-price -> ...--v2.
        listing = _parse("idealista_listing_renamed_price.html")
        self.assertEqual(listing.price_eur, 245_000)
        self.assertNotIn("price_eur", listing.missing_fields)

    def test_the_unmutated_fixture_still_parses_through_the_primary_selector(self) -> None:
        listing = _parse("idealista_listing.html")
        self.assertEqual(listing.price_eur, 245_000)


class TestRequiredFields(unittest.TestCase):
    def test_a_page_without_any_current_price_is_rejected_naming_the_field(self) -> None:
        with self.assertRaises(ListingRejected) as caught:
            _parse("idealista_listing_no_price.html")
        self.assertIn("price_eur", str(caught.exception))

    def test_the_previous_price_is_never_substituted_for_the_current_one(self) -> None:
        # The no-price fixture still carries pricedown_price=259.000; a fallback that matched it
        # would produce a plausible but wrong current price instead of a rejection.
        with self.assertRaises(ListingRejected):
            _parse("idealista_listing_no_price.html")

    def test_an_empty_page_is_rejected_rather_than_returned_half_filled(self) -> None:
        with self.assertRaises(ListingRejected):
            parse_listing_html("<html><body></body></html>", LISTING_URL, **CONTEXT)


class TestMissingFieldProvenance(unittest.TestCase):
    def test_fields_without_a_matching_selector_are_listed_in_missing_fields(self) -> None:
        html = """
        <div class="info-data"><span class="info-data-price">245.000</span></div>
        <div class="details-property_features"><ul><li>92 m² construidos</li></ul></div>
        """
        listing = parse_listing_html(html, LISTING_URL, **CONTEXT)
        self.assertIn("title", listing.missing_fields)
        self.assertIn("location", listing.missing_fields)
        self.assertNotIn("price_eur", listing.missing_fields)

    def test_a_complete_page_reports_no_missing_required_fields(self) -> None:
        listing = _parse("idealista_listing.html")
        for required in ("price_eur", "title", "location"):
            self.assertNotIn(required, listing.missing_fields)


class TestRecordContract(unittest.TestCase):
    def test_the_record_carries_crawl_context_and_drops_price_per_sqm(self) -> None:
        listing = _parse("idealista_listing.html")
        self.assertEqual(listing.operation, "sale")
        self.assertEqual(listing.municipality, "l-eliana")
        self.assertEqual(listing.observed_at, OBSERVED_AT)
        self.assertEqual(listing.extraction_version, "1")
        self.assertFalse(hasattr(listing, "price_per_sqm"))

    def test_the_page_district_is_kept_separate_from_the_crawl_context_district(self) -> None:
        # district comes from the SearchTarget and joins with ListingObservation; page_district is
        # what the listing itself claims. Conflating them would make the join meaningless.
        listing = _parse("idealista_listing.html")
        self.assertIsNone(listing.district)
        self.assertEqual(listing.page_district, "Ejemplo Norte")

    def test_the_record_is_frozen(self) -> None:
        import dataclasses

        listing = _parse("idealista_listing.html")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            listing.price_eur = 1


if __name__ == "__main__":
    unittest.main()
