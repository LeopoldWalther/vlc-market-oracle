"""Tests for the deterministic Idealista HTML listing parser."""

import unittest
from pathlib import Path

from src.idealista.listing_parser import PropertyListing, parse_listing_html

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "idealista_listing.html"
LISTING_URL = "https://www.idealista.com/inmueble/106749418/"


class TestParseListingHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.listing: PropertyListing = parse_listing_html(
            FIXTURE_PATH.read_text(encoding="utf-8"), LISTING_URL
        )

    def test_identity_is_derived_from_the_listing_url(self) -> None:
        self.assertEqual(self.listing.url, LISTING_URL)
        self.assertEqual(self.listing.idealista_id, "106749418")

    def test_prices_are_parsed_as_integers_in_euro(self) -> None:
        self.assertEqual(self.listing.price_eur, 245_000)
        self.assertEqual(self.listing.prev_price_eur, 259_000)
        self.assertEqual(self.listing.price_drop_pct, -5.5)
        self.assertEqual(self.listing.community_fee_eur_month, 45)
        self.assertAlmostEqual(self.listing.price_per_sqm, 245_000 / 92, places=6)

    def test_surface_and_room_features_are_parsed(self) -> None:
        self.assertEqual(self.listing.sqm_built, 92)
        self.assertEqual(self.listing.sqm_usable, 85)
        self.assertEqual(self.listing.rooms, 3)
        self.assertEqual(self.listing.bathrooms, 2)
        self.assertEqual(self.listing.floor, "4")
        self.assertTrue(self.listing.is_exterior)

    def test_amenity_flags_are_parsed(self) -> None:
        self.assertTrue(self.listing.has_elevator)
        self.assertTrue(self.listing.has_balcony)
        self.assertTrue(self.listing.has_parking)
        self.assertTrue(self.listing.has_ac)
        self.assertTrue(self.listing.has_fitted_wardrobes)
        self.assertTrue(self.listing.has_heating)
        self.assertEqual(self.listing.heating_type, "natural gas")
        self.assertEqual(self.listing.orientation, ["sur", "oeste"])
        self.assertEqual(self.listing.year_built, 1975)
        self.assertEqual(self.listing.condition, "good")

    def test_location_and_coordinates_are_parsed(self) -> None:
        self.assertEqual(self.listing.title, "Piso en calle de Ejemplo, 10")
        self.assertEqual(self.listing.location, "Barrio Ejemplo, Valencia")
        self.assertEqual(self.listing.neighborhood, "Ejemplo")
        self.assertEqual(self.listing.district, "Ejemplo Norte")
        self.assertEqual(self.listing.city, "Valencia")
        self.assertEqual(self.listing.latitude, 39.4625)
        self.assertEqual(self.listing.longitude, -0.3760)

    def test_description_paragraphs_are_joined(self) -> None:
        self.assertEqual(
            self.listing.description,
            "Luminoso piso reformado en 2020.\n\nCerca de transporte público y comercios.",
        )

    def test_raw_features_are_preserved_for_provenance(self) -> None:
        self.assertIn("3 habitaciones", self.listing.raw_features)
        self.assertEqual(len(self.listing.raw_features), 13)


class TestParseListingHtmlWithMissingFields(unittest.TestCase):
    def test_empty_page_yields_a_listing_without_derived_values(self) -> None:
        listing = parse_listing_html("<html><body></body></html>", LISTING_URL)

        self.assertEqual(listing.idealista_id, "106749418")
        self.assertIsNone(listing.price_eur)
        self.assertIsNone(listing.price_per_sqm)
        self.assertIsNone(listing.latitude)
        self.assertEqual(listing.title, "")
        self.assertEqual(listing.raw_features, [])


if __name__ == "__main__":
    unittest.main()
