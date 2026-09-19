"""Tests for aggregating extraction results into a CrawlReport with field coverage."""

import json
import unittest

from src.idealista.crawl_report import build_crawl_report, to_json


class TestCoverageRatios(unittest.TestCase):
    def test_a_field_missing_from_half_the_records_has_50_percent_coverage(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale",
            missing_fields_per_record=[(), ("price_eur",), (), ("price_eur",)],
            thresholds={"price_eur": 0.9},
        )
        self.assertEqual(report.coverage["price_eur"], 0.5)

    def test_a_field_never_missing_has_full_coverage(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale",
            missing_fields_per_record=[(), (), ()],
            thresholds={"price_eur": 0.9},
        )
        self.assertEqual(report.coverage["price_eur"], 1.0)

    def test_only_fields_with_a_configured_threshold_are_tracked(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale",
            missing_fields_per_record=[("rooms",)],
            thresholds={"price_eur": 0.9},
        )
        self.assertNotIn("rooms", report.coverage)

    def test_zero_records_does_not_raise_and_reports_full_coverage(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale", missing_fields_per_record=[], thresholds={"price_eur": 0.9}
        )
        self.assertEqual(report.coverage["price_eur"], 1.0)
        self.assertFalse(report.failed)


class TestThresholdBreach(unittest.TestCase):
    def test_coverage_below_threshold_fails_the_report_and_names_the_field(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale",
            missing_fields_per_record=[("price_eur",)] * 3 + [()],
            thresholds={"price_eur": 0.9},
        )
        self.assertTrue(report.failed)
        self.assertIn("price_eur", report.failed_fields)

    def test_coverage_at_or_above_every_threshold_leaves_the_report_unfailed(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale",
            missing_fields_per_record=[()] * 9 + [("price_eur",)],
            thresholds={"price_eur": 0.9},
        )
        self.assertFalse(report.failed)
        self.assertEqual(report.failed_fields, ())

    def test_coverage_exactly_at_the_threshold_does_not_fail(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale",
            missing_fields_per_record=[("rooms",)] + [()] * 9,
            thresholds={"rooms": 0.9},
        )
        self.assertFalse(report.failed)

    def test_multiple_breached_fields_are_all_named(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale",
            missing_fields_per_record=[("price_eur", "rooms")],
            thresholds={"price_eur": 0.9, "rooms": 0.9},
        )
        self.assertEqual(set(report.failed_fields), {"price_eur", "rooms"})


class TestReportMetadataAndSerialization(unittest.TestCase):
    def test_the_report_carries_the_run_metadata_it_is_given(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale",
            missing_fields_per_record=[(), ()],
            thresholds={},
            requests=12,
            credits_spent=300,
            pages=4,
            quarantined=1,
            errors_by_category={"challenge": 1},
        )
        self.assertEqual(report.target, "l-eliana-sale")
        self.assertEqual(report.records, 2)
        self.assertEqual(report.requests, 12)
        self.assertEqual(report.credits_spent, 300)
        self.assertEqual(report.pages, 4)
        self.assertEqual(report.quarantined, 1)
        self.assertEqual(report.errors_by_category, {"challenge": 1})

    def test_serializes_to_json_with_every_documented_field(self) -> None:
        report = build_crawl_report(
            "l-eliana-sale",
            missing_fields_per_record=[()],
            thresholds={"price_eur": 0.9},
            requests=1,
            credits_spent=25,
            pages=1,
            quarantined=0,
            errors_by_category={},
        )
        payload = json.loads(to_json(report))
        for key in (
            "target",
            "requests",
            "credits_spent",
            "pages",
            "records",
            "quarantined",
            "errors_by_category",
            "coverage",
            "failed",
            "failed_fields",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["requests"], 1)
        self.assertEqual(payload["coverage"]["price_eur"], 1.0)


if __name__ == "__main__":
    unittest.main()
