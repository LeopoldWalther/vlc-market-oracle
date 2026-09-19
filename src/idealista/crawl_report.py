"""Aggregate a run's extraction results into a CrawlReport with per-field coverage.

Pure: no network, no filesystem, no mutation of an existing report. The caller decides what to do
with `report.failed` (e.g. a non-zero process exit); this module only builds and serializes.
"""

import dataclasses
import json
from typing import Mapping, Optional, Sequence

from src.idealista.models import CrawlReport


def build_crawl_report(
    target: str,
    missing_fields_per_record: Sequence[Sequence[str]],
    *,
    thresholds: Mapping[str, float],
    requests: int = 0,
    credits_spent: int = 0,
    pages: int = 0,
    quarantined: int = 0,
    errors_by_category: Optional[Mapping[str, int]] = None,
) -> CrawlReport:
    """Build a report from one `missing_fields` collection per produced record.

    Only fields named in `thresholds` are tracked, so the threshold configuration is the tracked
    field set; a field never listed is neither reported nor able to fail the run. With zero
    records every tracked field is reported as fully covered, since there is nothing to erode.
    """
    total = len(missing_fields_per_record)
    coverage: dict[str, float] = {}
    failed_fields: list[str] = []

    for field, threshold in thresholds.items():
        if total == 0:
            ratio = 1.0
        else:
            missing_count = sum(1 for missing in missing_fields_per_record if field in missing)
            ratio = (total - missing_count) / total
        coverage[field] = ratio
        if ratio < threshold:
            failed_fields.append(field)

    return CrawlReport(
        target=target,
        requests=requests,
        credits_spent=credits_spent,
        pages=pages,
        records=total,
        quarantined=quarantined,
        errors_by_category=dict(errors_by_category or {}),
        coverage=coverage,
        failed=bool(failed_fields),
        failed_fields=tuple(sorted(failed_fields)),
    )


def to_json(report: CrawlReport) -> str:
    """Serialize a CrawlReport to JSON, tuples included as arrays."""
    return json.dumps(dataclasses.asdict(report))
