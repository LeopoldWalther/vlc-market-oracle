"""Turn one Idealista search results page into listing observations.

Pure: takes HTML, a search target, the requested page URL and an injected clock. No network, no
filesystem. Every selector comes from the registry in `selectors.py`.
"""

import re
from typing import NamedTuple, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from src.idealista import selectors
from src.idealista.models import ListingObservation, SearchTarget
from src.idealista.selectors import resolve_field

_LISTING_ID_IN_HREF = re.compile(r"/inmueble/(\d+)")
_ROOMS = re.compile(r"(\d+)\s*hab", re.IGNORECASE)
_SQM = re.compile(r"(\d+)\s*m²", re.IGNORECASE)


class SearchPageParseResult(NamedTuple):
    observations: tuple[ListingObservation, ...]
    next_page_url: Optional[str]
    result_count: Optional[int]
    drift: tuple[str, ...]


def _first(tree: Tag, registry: selectors.SelectorRegistry, key: str) -> Optional[Tag]:
    for selector in registry[key]:
        element = tree.select_one(selector)
        if element is not None:
            return element
    return None


def _int_from(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _pct_from(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", text)
    return float(match.group(0).replace(",", ".")) if match else None


def _measure(card: Tag, pattern: re.Pattern[str]) -> Optional[int]:
    """Match a measurement by its unit keyword, never by position.

    A card reads "Garaje incluido | 4 hab. | 200 m2 | 3a planta ... | 22 horas": the first token is
    often non-numeric and several later ones contain digits of their own.
    """
    for selector in selectors.SEARCH_CARD["detail_char_item"]:
        for item in card.select(selector):
            match = pattern.search(item.get_text(" ", strip=True))
            if match:
                return int(match.group(1))
    return None


def _card_to_observation(
    card: Tag, target: SearchTarget, origin: str, observed_at
) -> tuple[Optional[ListingObservation], Optional[str]]:
    element_id = (card.get("data-element-id") or "").strip()
    link = _first(card, selectors.SEARCH_CARD, "listing_link")
    href = link.get("href") if link is not None else ""
    href_match = _LISTING_ID_IN_HREF.search(href or "")
    href_id = href_match.group(1) if href_match else None

    drift = None
    if href_id is not None and element_id and href_id != element_id:
        drift = (
            f"listing id drift: data-element-id={element_id} but item-link href carries {href_id}"
        )

    listing_id = element_id or href_id
    if not listing_id:
        return None, "card without a listing id in either data-element-id or the item-link href"

    price_text, _ = resolve_field(card, selectors.SEARCH_CARD["price"])
    prev_text, _ = resolve_field(card, selectors.SEARCH_CARD["prev_price"])
    drop_text, _ = resolve_field(card, selectors.SEARCH_CARD["price_drop"])
    freshness_text, _ = resolve_field(card, selectors.SEARCH_CARD["freshness"])

    observation = ListingObservation(
        listing_id=listing_id,
        listing_url=f"{origin}/inmueble/{listing_id}/",
        operation=target.operation,
        municipality=target.municipality,
        district=target.district,
        price_eur=_int_from(price_text),
        prev_price_eur=_int_from(prev_text),
        price_drop_pct=_pct_from(drop_text),
        sqm_built=_measure(card, _SQM),
        rooms=_measure(card, _ROOMS),
        freshness_label=freshness_text,
        observed_at=observed_at,
    )
    return observation, drift


def _next_page_url(soup: Tag, page_url: str) -> Optional[str]:
    link = _first(soup, selectors.SEARCH_PAGE, "next_page")
    if link is None:
        return None

    absolute = urljoin(page_url, link.get("href") or "")
    # Measured in task 0.3: the canonical ?ordenado-por=... form is preserved in the next href,
    # the bare ?fecha-publicacion-desc form is not. Carrying the query over keeps page 2 sorted.
    requested_query = urlsplit(page_url).query
    parts = urlsplit(absolute)
    if requested_query and not parts.query:
        absolute = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, requested_query, parts.fragment)
        )
    return absolute


def parse_search_page(
    html: str, target: SearchTarget, page_url: str, observed_at
) -> SearchPageParseResult:
    """Parse one search results page into observations plus pagination and count metadata."""
    soup = BeautifulSoup(html, "html.parser")
    page_parts = urlsplit(page_url)
    origin = f"{page_parts.scheme}://{page_parts.netloc}"

    observations: list[ListingObservation] = []
    drift: list[str] = []
    container = _first(soup, selectors.SEARCH_PAGE, "results_container") or soup
    cards: list[Tag] = []
    for selector in selectors.SEARCH_PAGE["card"]:
        cards = container.select(selector)
        if cards:
            break
    for card in cards:
        observation, card_drift = _card_to_observation(card, target, origin, observed_at)
        if card_drift:
            drift.append(card_drift)
        if observation is not None:
            observations.append(observation)

    count_text, _ = resolve_field(soup, selectors.SEARCH_PAGE["result_count"])

    return SearchPageParseResult(
        observations=tuple(observations),
        next_page_url=_next_page_url(soup, page_url),
        result_count=_int_from(count_text.split()[0] if count_text else None),
        drift=tuple(drift),
    )
