"""Derive the month-to-date credit spend from the run reports already on disk.

A per-run budget does not protect a monthly quota: several runs, each within budget, can still
exhaust the allowance, and the Free plan does not roll credits over. The run reports are the
ledger, so reading them back adds no second source of truth and no new failure mode.

Pure over a directory path plus a reference instant: no clock, no network, no writes.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .zenrows_source import CREDIT_BUDGET_EXHAUSTED

MONTHLY_BUDGET_EXHAUSTED = "monthly_budget_exhausted"

_PARTITION_PREFIX = "observed_date="
_REPORT_SUFFIX = "*.jsonl"


@dataclass(frozen=True)
class MonthlyAllowance:
    """What the current UTC month has already cost and what is left of the quota."""

    monthly_budget: int
    month_to_date: int
    remaining: int
    exhausted: bool


@dataclass(frozen=True)
class BindingBudget:
    """The tighter of the run budget and the monthly remainder, plus why a stop would happen."""

    credits: int
    reason: str


def month_to_date_credits(runs_root: Path, reference: datetime) -> int:
    """Sum ``credits_spent`` across the run reports of ``reference``'s UTC month.

    A runs directory that does not exist yet means no run has happened, which is a spend of zero
    rather than an error.
    """
    _require_utc(reference)

    month_partitions = f"{_PARTITION_PREFIX}{reference.year:04d}-{reference.month:02d}-*"
    total = 0
    for report in Path(runs_root).rglob(f"{month_partitions}/{_REPORT_SUFFIX}"):
        for line in report.read_text(encoding="utf-8").splitlines():
            if line.strip():
                total += int(json.loads(line)["credits_spent"])
    return total


def monthly_allowance(
    runs_root: Path, *, monthly_budget: int, reference: datetime
) -> MonthlyAllowance:
    """Report how much of ``monthly_budget`` the current UTC month has left."""
    spent = month_to_date_credits(runs_root, reference)
    remaining = max(monthly_budget - spent, 0)
    return MonthlyAllowance(
        monthly_budget=monthly_budget,
        month_to_date=spent,
        remaining=remaining,
        exhausted=remaining == 0,
    )


def binding_budget(
    runs_root: Path, *, monthly_budget: int, run_budget: int, reference: datetime
) -> BindingBudget:
    """Return the credit budget a run may actually spend, and the reason it would stop."""
    allowance = monthly_allowance(
        runs_root, monthly_budget=monthly_budget, reference=reference
    )
    if allowance.remaining <= run_budget:
        return BindingBudget(allowance.remaining, MONTHLY_BUDGET_EXHAUSTED)
    return BindingBudget(run_budget, CREDIT_BUDGET_EXHAUSTED)


def _require_utc(reference: datetime) -> None:
    if reference.tzinfo is None or reference.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"reference must be timezone-aware UTC, got {reference!r}")
