"""Tests for the frozen crawl value objects: SearchTarget, ListingObservation,
ListingDetail and CrawlReport.
"""

import dataclasses
import unittest
from datetime import datetime, timedelta, timezone

from src.idealista.models import (
    CrawlReport,
    ListingDetail,
    ListingObservation,
    SearchTarget,
)

UTC_NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _make_observation(**overrides) -> ListingObservation:
    fields = dict(
        listing_id="111804117",
        listing_url="https://www.idealista.com/inmueble/111804117/",
        operation="rent",
        municipality="l-eliana",
        district=None,
        price_eur=1_225,
        prev_price_eur=None,
        price_drop_pct=None,
        sqm_built=81,
        rooms=1,
        freshness_label="6 horas",
        observed_at=UTC_NOW,
    )
    fields.update(overrides)
    return ListingObservation(**fields)


def _make_detail(**overrides) -> ListingDetail:
    fields = dict(
        url="https://www.idealista.com/inmueble/111804117/",
        idealista_id="111804117",
        operation="rent",
        municipality="l-eliana",
        district=None,
        observed_at=UTC_NOW,
        extraction_version="1",
    )
    fields.update(overrides)
    return ListingDetail(**fields)


class TestSearchTarget(unittest.TestCase):
    def test_accepts_sale_and_rent(self) -> None:
        for operation in ("sale", "rent"):
            target = SearchTarget(
                municipality="l-eliana",
                district=None,
                operation=operation,
                base_url="https://www.idealista.com/venta-viviendas/l-eliana-valencia/",
            )
            self.assertEqual(target.operation, operation)

    def test_rejects_an_operation_outside_sale_or_rent(self) -> None:
        with self.assertRaises(ValueError):
            SearchTarget(
                municipality="l-eliana",
                district=None,
                operation="venta",
                base_url="https://www.idealista.com/venta-viviendas/l-eliana-valencia/",
            )

    def test_rejects_a_blank_base_url(self) -> None:
        with self.assertRaises(ValueError):
            SearchTarget(municipality="l-eliana", district=None, operation="sale", base_url="")

    def test_expected_listings_above_the_search_cap_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SearchTarget(
                municipality="valencia",
                district="extramurs",
                operation="sale",
                base_url="https://www.idealista.com/venta-viviendas/valencia/extramurs/",
                expected_listings=1_801,
            )

    def test_is_frozen(self) -> None:
        target = SearchTarget(
            municipality="l-eliana",
            district=None,
            operation="sale",
            base_url="https://www.idealista.com/venta-viviendas/l-eliana-valencia/",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            target.operation = "rent"


class TestListingObservation(unittest.TestCase):
    def test_carries_every_required_field(self) -> None:
        observation = _make_observation()
        self.assertEqual(observation.listing_id, "111804117")
        self.assertEqual(observation.freshness_label, "6 horas")
        self.assertEqual(observation.observed_at, UTC_NOW)

    def test_freshness_label_is_optional(self) -> None:
        observation = _make_observation(freshness_label=None)
        self.assertIsNone(observation.freshness_label)

    def test_rejects_a_blank_listing_id(self) -> None:
        with self.assertRaises(ValueError):
            _make_observation(listing_id="")

    def test_rejects_a_negative_price(self) -> None:
        with self.assertRaises(ValueError):
            _make_observation(price_eur=-1)

    def test_rejects_a_naive_observed_at(self) -> None:
        with self.assertRaises(ValueError):
            _make_observation(observed_at=datetime(2026, 9, 19, 12, 0))

    def test_rejects_a_non_utc_observed_at(self) -> None:
        madrid = timezone(timedelta(hours=2))
        with self.assertRaises(ValueError):
            _make_observation(observed_at=datetime(2026, 9, 19, 14, 0, tzinfo=madrid))

    def test_is_frozen(self) -> None:
        observation = _make_observation()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            observation.price_eur = 999


class TestListingDetail(unittest.TestCase):
    def test_carries_provenance_fields(self) -> None:
        detail = _make_detail()
        self.assertEqual(detail.idealista_id, "111804117")
        self.assertEqual(detail.operation, "rent")
        self.assertEqual(detail.extraction_version, "1")
        self.assertEqual(detail.missing_fields, ())

    def test_has_no_price_per_sqm_field(self) -> None:
        detail = _make_detail()
        self.assertFalse(hasattr(detail, "price_per_sqm"))

    def test_rejects_a_blank_idealista_id(self) -> None:
        with self.assertRaises(ValueError):
            _make_detail(idealista_id="")

    def test_rejects_a_naive_observed_at(self) -> None:
        with self.assertRaises(ValueError):
            _make_detail(observed_at=datetime(2026, 9, 19, 12, 0))

    def test_is_frozen(self) -> None:
        detail = _make_detail()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            detail.title = "changed"


class TestCrawlReport(unittest.TestCase):
    def test_constructs_with_only_a_target_name(self) -> None:
        report = CrawlReport(target="l-eliana-rent")
        self.assertEqual(report.target, "l-eliana-rent")

    def test_is_frozen(self) -> None:
        report = CrawlReport(target="l-eliana-rent")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.target = "other"


if __name__ == "__main__":
    unittest.main()
