"""Tests for the monthly credit quota derived from prior run reports."""

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.idealista.credit_ledger import (
    MONTHLY_BUDGET_EXHAUSTED,
    binding_budget,
    month_to_date_credits,
    monthly_allowance,
)
from src.idealista.zenrows_source import (
    CREDIT_BUDGET_EXHAUSTED,
    CreditBudgetExhausted,
    ZenRowsFetcher,
)

FEBRUARY = datetime(2026, 2, 17, 6, 0, tzinfo=timezone.utc)
SEARCH_URL = "https://www.idealista.com/alquiler-viviendas/l-eliana-valencia/"


class _FakeResponse:
    status_code = 200
    text = "<html>ok</html>"


def _always_ok(url, *, params, timeout):
    return _FakeResponse()


class _LedgerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runs_root = Path(self._tmp.name) / "runs"

    def write_report(self, observed_date: str, name: str, *credits: int) -> None:
        directory = self.runs_root / "operation=rent" / f"observed_date={observed_date}"
        directory.mkdir(parents=True, exist_ok=True)
        lines = [
            '{"target": "l-eliana", "credits_spent": %d, "requests": 4}' % amount
            for amount in credits
        ]
        (directory / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestMonthToDateCredits(_LedgerTestCase):
    def test_it_sums_every_report_of_the_current_utc_month(self) -> None:
        self.write_report("2026-02-03", "l-eliana", 1200)
        self.write_report("2026-02-10", "l-eliana", 800, 450)

        self.assertEqual(month_to_date_credits(self.runs_root, FEBRUARY), 2450)

    def test_reports_of_a_previous_month_are_excluded(self) -> None:
        """The Free allowance does not roll over, so January spend is irrelevant in February."""
        self.write_report("2026-01-28", "l-eliana", 4900)
        self.write_report("2026-02-03", "l-eliana", 1200)

        self.assertEqual(month_to_date_credits(self.runs_root, FEBRUARY), 1200)

    def test_reports_of_a_later_month_are_excluded(self) -> None:
        self.write_report("2026-03-01", "l-eliana", 3000)

        self.assertEqual(month_to_date_credits(self.runs_root, FEBRUARY), 0)

    def test_a_missing_report_directory_counts_as_no_spend(self) -> None:
        self.assertEqual(month_to_date_credits(self.runs_root, FEBRUARY), 0)

    def test_a_naive_reference_time_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            month_to_date_credits(self.runs_root, datetime(2026, 2, 17, 6, 0))


class TestMonthlyAllowance(_LedgerTestCase):
    def test_it_reports_what_is_left_of_the_monthly_quota(self) -> None:
        self.write_report("2026-02-03", "l-eliana", 1200)
        self.write_report("2026-02-10", "l-eliana", 800)

        allowance = monthly_allowance(
            self.runs_root, monthly_budget=5000, reference=FEBRUARY
        )

        self.assertEqual(allowance.month_to_date, 2000)
        self.assertEqual(allowance.remaining, 3000)
        self.assertFalse(allowance.exhausted)

    def test_an_overspent_month_reports_zero_rather_than_a_negative_allowance(self) -> None:
        self.write_report("2026-02-03", "l-eliana", 5200)

        allowance = monthly_allowance(
            self.runs_root, monthly_budget=5000, reference=FEBRUARY
        )

        self.assertEqual(allowance.remaining, 0)
        self.assertTrue(allowance.exhausted)


class TestBindingBudget(_LedgerTestCase):
    def test_the_run_budget_binds_while_the_month_has_room(self) -> None:
        self.write_report("2026-02-03", "l-eliana", 1000)

        budget = binding_budget(
            self.runs_root, monthly_budget=5000, run_budget=500, reference=FEBRUARY
        )

        self.assertEqual(budget.credits, 500)
        self.assertEqual(budget.reason, CREDIT_BUDGET_EXHAUSTED)

    def test_the_monthly_remainder_binds_once_it_is_the_tighter_bound(self) -> None:
        self.write_report("2026-02-03", "l-eliana", 4800)

        budget = binding_budget(
            self.runs_root, monthly_budget=5000, run_budget=500, reference=FEBRUARY
        )

        self.assertEqual(budget.credits, 200)
        self.assertEqual(budget.reason, MONTHLY_BUDGET_EXHAUSTED)


class TestRunStopsOnTheMonthlyRemainder(_LedgerTestCase):
    def test_a_third_run_stops_once_the_month_is_exhausted(self) -> None:
        self.write_report("2026-02-03", "l-eliana", 2500)
        self.write_report("2026-02-10", "l-eliana", 2450)

        budget = binding_budget(
            self.runs_root, monthly_budget=5000, run_budget=1000, reference=FEBRUARY
        )
        fetcher = ZenRowsFetcher(
            "test-api-key",
            credit_budget=budget.credits,
            budget_reason=budget.reason,
            http_get=_always_ok,
            sleep=lambda seconds: None,
            pause_seconds=0.0,
        )

        fetcher.fetch(SEARCH_URL)
        fetcher.fetch(SEARCH_URL)
        with self.assertRaises(CreditBudgetExhausted) as stop:
            fetcher.fetch(SEARCH_URL)

        self.assertEqual(budget.credits, 50)
        self.assertEqual(fetcher.credits_spent, 50)
        self.assertEqual(stop.exception.reason, MONTHLY_BUDGET_EXHAUSTED)
        self.assertEqual(fetcher.stopped_reason, "monthly_budget_exhausted")


if __name__ == "__main__":
    unittest.main()
