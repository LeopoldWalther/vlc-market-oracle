"""Deterministic extraction of an Idealista listing detail page from static HTML.

Pure functions only: no network, no browser. Callers supply HTML from a source
adapter (e.g. ZenRows) or from a recorded fixture.
"""

import re
from typing import Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from src.idealista import selectors
from src.idealista.models import ListingDetail
from src.idealista.selectors import resolve_field


class ListingRejected(Exception):
    """Raised when a detail page lacks a required field.

    A half-filled record is worse than none: it looks healthy downstream while silently carrying a
    gap. The caller quarantines the raw HTML instead.
    """


_DIRECTIONS = (
    "noreste",
    "noroeste",
    "sureste",
    "suroeste",
    "norte",
    "sur",
    "este",
    "oeste",
)


def _extract_idealista_id_from_url(url: str) -> str:
    match = re.search(r"/inmueble/(\d+)", url)
    return match.group(1) if match else ""


def _parse_int_from_text(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def _parse_pct_from_text(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", "."))
    return float(match.group(0)) if match else None


def _parse_orientations(feature_text: str) -> list[str]:
    found: list[str] = []
    for direction in _DIRECTIONS:
        if re.search(rf"\b{direction}\b", feature_text) and direction not in found:
            found.append(direction)
    return found


def _parse_coords_from_text(text: str) -> tuple[Optional[float], Optional[float]]:
    patterns = (
        r"[?&]center=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)",
        r"markers=[^&]*?(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)",
        r"LatLng\((-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1)), float(match.group(2))
    return None, None


def parse_features(raw_features: list[str]) -> dict:
    """Map Idealista feature bullet points onto typed listing attributes."""
    result: dict = {
        "sqm_built": None,
        "sqm_usable": None,
        "rooms": None,
        "bathrooms": None,
        "floor": None,
        "is_exterior": None,
        "orientation": [],
        "year_built": None,
        "condition": None,
        "has_balcony": False,
        "has_elevator": False,
        "has_ac": False,
        "has_fitted_wardrobes": False,
        "has_parking": False,
        "has_heating": None,
        "heating_type": None,
    }

    for feature in raw_features:
        f = feature.lower().strip()

        m = re.search(r"(\d+)\s*m²\s*construidos", f)
        if m:
            result["sqm_built"] = int(m.group(1))

        m = re.search(r"(\d+)\s*m²\s*[uú]tiles", f)
        if m:
            result["sqm_usable"] = int(m.group(1))

        m = re.search(r"(\d+)\s*habitacion", f)
        if m:
            result["rooms"] = int(m.group(1))

        m = re.search(r"(\d+)\s*ba[ñn]", f)
        if m:
            result["bathrooms"] = int(m.group(1))

        # Idealista writes both "4ª planta" and "Planta 4ª".
        m = re.search(r"(\d+)\s*[aª°]?\s*planta|planta\s*(\d+)\s*[aª°]?", f)
        if m:
            result["floor"] = m.group(1) or m.group(2)

        if "exterior" in f:
            result["is_exterior"] = True
        elif "interior" in f and result["is_exterior"] is None:
            result["is_exterior"] = False

        m = re.search(r"construido en\s*(\d{4})", f)
        if m:
            result["year_built"] = int(m.group(1))

        if "para reformar" in f:
            result["condition"] = "needs_renovation"
        elif "buen estado" in f or "segunda mano" in f:
            result["condition"] = "good"
        elif "obra nueva" in f or "nuevo" in f:
            result["condition"] = "new"

        if "balc" in f:
            result["has_balcony"] = True
        if "ascensor" in f:
            result["has_elevator"] = True
        if "aire acondicionado" in f:
            result["has_ac"] = True
        if "armarios empotrados" in f:
            result["has_fitted_wardrobes"] = True
        if "garaje" in f or "parking" in f:
            result["has_parking"] = True

        if "no dispone de calefacci" in f or "sin calefacci" in f:
            result["has_heating"] = False
            result["heating_type"] = None
        elif "calefacci" in f:
            if result["has_heating"] is None:
                result["has_heating"] = True
            if "gas natural" in f:
                result["heating_type"] = "natural gas"

        if "orientaci" in f:
            parsed_orientations = _parse_orientations(f)
            if parsed_orientations:
                result["orientation"] = parsed_orientations

    return result


def _extract_raw_features(soup: BeautifulSoup) -> list[str]:
    items = soup.select("[class*='details-property_features'] li")
    return [text for item in items if (text := item.get_text(" ", strip=True))]


def _extract_community_fee_eur_month(soup: BeautifulSoup) -> int | None:
    for row in soup.select(".price-features__container .flex-feature"):
        label = row.select_one(".flex-feature-text")
        detail = row.select_one(".flex-feature-details")
        if label is None or detail is None:
            continue
        if "gastos de comunidad" in label.get_text(" ", strip=True).lower():
            return _parse_int_from_text(detail.get_text(" ", strip=True))
    return None


def _extract_location_parts(
    soup: BeautifulSoup,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    items = soup.select("#headerMap [class*='header-map-list']")
    texts = [text for item in items if (text := item.get_text(" ", strip=True))]

    neighborhood: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None

    for text in texts:
        lower_text = text.lower()
        if lower_text.startswith("barrio "):
            neighborhood = text.split(" ", 1)[1].strip()
        elif lower_text.startswith("distrito "):
            district = text.split(" ", 1)[1].strip()
        elif lower_text.startswith("valencia"):
            city = "Valencia"

    if city is None and texts:
        city = texts[-1].split(",")[0].strip()

    return neighborhood, district, city


def _extract_coordinates(
    soup: BeautifulSoup, html: str
) -> tuple[Optional[float], Optional[float]]:
    candidates: list[str] = []
    for image in soup.select("img#sMap, #map img[src*='staticmap']"):
        if isinstance(image, Tag) and (src := image.get("src")):
            candidates.append(str(src))
    for link in soup.select("a[class*='showMap']"):
        if isinstance(link, Tag) and (href := link.get("href")):
            candidates.append(str(href))
    candidates.append(html)

    for candidate in candidates:
        latitude, longitude = _parse_coords_from_text(unquote(candidate))
        if latitude is not None and longitude is not None:
            return latitude, longitude
    return None, None


def _extract_description(soup: BeautifulSoup) -> str:
    paragraphs = soup.select("[class*='adCommentsLanguage'] p")
    parts = [text for p in paragraphs if (text := p.get_text("\n", strip=True))]
    return "\n\n".join(parts)


def parse_listing_html(
    html: str,
    listing_url: str,
    *,
    operation: str,
    municipality: str,
    district: Optional[str],
    observed_at,
    extraction_version: str,
) -> ListingDetail:
    """Parse one Idealista detail page into a listing detail record.

    Fields resolve through the ordered selector registry, so a renamed class falls back instead of
    silently yielding None. Every unresolved field is named in ``missing_fields``. A record missing
    a required field is rejected rather than written half-filled.
    """
    soup = BeautifulSoup(html, "html.parser")

    raw_features = _extract_raw_features(soup)
    features = parse_features(raw_features)

    resolved: dict[str, Optional[str]] = {}
    missing_fields: list[str] = []
    for field_name, candidates in selectors.DETAIL_PAGE.items():
        text, _ = resolve_field(soup, candidates)
        resolved[field_name] = text
        if text is None:
            missing_fields.append(field_name)

    price_eur = _parse_int_from_text(resolved["price_eur"])
    sqm_built = features["sqm_built"]
    idealista_id = _extract_idealista_id_from_url(listing_url)

    for name, value in (
        ("idealista_id", idealista_id),
        ("price_eur", price_eur),
        ("sqm_built", sqm_built),
    ):
        if not value:
            raise ListingRejected(
                f"{listing_url} is missing the required field {name}; quarantined instead of "
                "written as a partial record"
            )

    neighborhood, page_district, city = _extract_location_parts(soup)
    latitude, longitude = _extract_coordinates(soup, html)

    return ListingDetail(
        url=listing_url,
        idealista_id=idealista_id,
        operation=operation,
        municipality=municipality,
        district=district,
        observed_at=observed_at,
        extraction_version=extraction_version,
        price_eur=price_eur,
        prev_price_eur=_parse_int_from_text(resolved["prev_price_eur"]),
        price_drop_pct=_parse_pct_from_text(resolved["price_drop_pct"]),
        community_fee_eur_month=_extract_community_fee_eur_month(soup),
        sqm_built=sqm_built,
        sqm_usable=features["sqm_usable"],
        rooms=features["rooms"],
        bathrooms=features["bathrooms"],
        floor=features["floor"],
        is_exterior=features["is_exterior"],
        orientation=tuple(features["orientation"]),
        has_elevator=features["has_elevator"],
        has_balcony=features["has_balcony"],
        has_parking=features["has_parking"],
        has_ac=features["has_ac"],
        has_fitted_wardrobes=features["has_fitted_wardrobes"],
        has_heating=features["has_heating"],
        heating_type=features["heating_type"],
        title=resolved["title"] or "",
        location=resolved["location"] or "",
        description=_extract_description(soup),
        neighborhood=neighborhood,
        page_district=page_district,
        city=city,
        latitude=latitude,
        longitude=longitude,
        year_built=features["year_built"],
        condition=features["condition"],
        raw_features=tuple(raw_features),
        missing_fields=tuple(missing_fields),
    )
