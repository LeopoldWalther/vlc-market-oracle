"""Frozen value objects shared by the crawler, parsers and the writer.

Validation lives at construction, matching the repository's boundary-validation rule. FEATURE-002
persists these records as-is, so their field names are the shared contract with that feature.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_OPERATIONS = frozenset({"sale", "rent"})
_MAX_LISTINGS_PER_SEARCH = 1_800


def _require_operation(operation: str) -> None:
    if operation not in _OPERATIONS:
        raise ValueError(f"operation must be one of {sorted(_OPERATIONS)}, got {operation!r}")


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC, got a naive datetime")
    if value.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{field_name} must be UTC, got a {value.utcoffset()} offset")


def _require_non_negative(value: Optional[int], field_name: str) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{field_name} must not be negative, got {value}")


@dataclass(frozen=True)
class SearchTarget:
    """One paginated Idealista search: configuration, not code."""

    municipality: str
    district: Optional[str]
    operation: str
    base_url: str
    expected_listings: Optional[int] = None

    def __post_init__(self) -> None:
        _require_operation(self.operation)
        if not self.base_url:
            raise ValueError("base_url must not be blank")
        if self.expected_listings is not None and self.expected_listings > _MAX_LISTINGS_PER_SEARCH:
            raise ValueError(
                f"expected_listings={self.expected_listings} exceeds the "
                f"{_MAX_LISTINGS_PER_SEARCH}-listing search cap; split this target"
            )


@dataclass(frozen=True)
class ListingObservation:
    """One row per listing per observation day, read straight off a search card."""

    listing_id: str
    listing_url: str
    operation: str
    municipality: str
    district: Optional[str]
    price_eur: Optional[int]
    prev_price_eur: Optional[int]
    price_drop_pct: Optional[float]
    sqm_built: Optional[int]
    rooms: Optional[int]
    freshness_label: Optional[str]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.listing_id:
            raise ValueError("listing_id must not be blank")
        _require_operation(self.operation)
        _require_non_negative(self.price_eur, "price_eur")
        _require_non_negative(self.prev_price_eur, "prev_price_eur")
        _require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True)
class ListingDetail:
    """The full attribute set of one listing, written once per listing_id.

    Mirrors PropertyListing plus provenance fields; price_per_sqm is deliberately absent because it
    is derived and, as a float, incompatible with the money rule.
    """

    url: str
    idealista_id: str
    operation: str
    municipality: str
    district: Optional[str]
    observed_at: datetime
    extraction_version: str

    price_eur: Optional[int] = None
    prev_price_eur: Optional[int] = None
    price_drop_pct: Optional[float] = None
    community_fee_eur_month: Optional[int] = None

    sqm_built: Optional[int] = None
    sqm_usable: Optional[int] = None

    rooms: Optional[int] = None
    bathrooms: Optional[int] = None
    floor: Optional[str] = None
    is_exterior: Optional[bool] = None
    orientation: tuple[str, ...] = field(default_factory=tuple)
    has_elevator: bool = False
    has_balcony: bool = False
    has_parking: bool = False
    has_ac: bool = False
    has_fitted_wardrobes: bool = False
    has_heating: Optional[bool] = None
    heating_type: Optional[str] = None

    title: str = ""
    location: str = ""
    description: str = ""
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    year_built: Optional[int] = None
    condition: Optional[str] = None

    raw_features: tuple[str, ...] = field(default_factory=tuple)
    missing_fields: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.idealista_id:
            raise ValueError("idealista_id must not be blank")
        _require_operation(self.operation)
        _require_utc(self.observed_at, "observed_at")


@dataclass(frozen=True)
class CrawlReport:
    """The run report for one search target.

    Deliberately minimal: later tasks (coverage thresholds, the credit ledger, pagination) each add
    the fields their own behavior needs.
    """

    target: str
