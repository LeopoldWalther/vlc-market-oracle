"""An ordered selector registry: each field maps to CSS selectors tried in order.

The mechanism is deliberately dumb: a layout change becomes a data edit to a selector list, not a
code change to a parser. Operates on an already-parsed tree; no network, no filesystem.
"""

from typing import NamedTuple, Optional, Sequence

from bs4 import Tag

SelectorRegistry = dict[str, list[str]]

# Confirmed against live captures in task 0.3. Each list is tried in order, so adding a fallback
# after a layout change is an edit here rather than a change to any parser.
SEARCH_PAGE: SelectorRegistry = {
    "results_container": ["section.items-container"],
    "card": ["article.item[data-element-id]"],
    "result_count": ["span#h1-container__text"],
    "next_page": ["div.pagination li.next > a[href]"],
}

SEARCH_CARD: SelectorRegistry = {
    "listing_link": ["a.item-link[href]"],
    "price": ["span.item-price"],
    # item-price-by-area also lives in the price row on sale pages and must never be read as a
    # previous price, so both are addressed by their own class rather than by position.
    "prev_price": ["span.pricedown_price"],
    "price_drop": ["span.pricedown_icon"],
    "detail_chars": ["div.item-detail-char"],
    "detail_char_item": ["span.item-detail"],
    "freshness": ["span.item-detail.txt-highlight-red"],
}


class ResolvedField(NamedTuple):
    text: Optional[str]
    matched_selector: Optional[str]


def resolve_field(tree: Tag, selectors: Sequence[str]) -> ResolvedField:
    """Return the text of the first selector in `selectors` that matches `tree`.

    Selectors are tried in order; the first match wins. Neither a match nor the absence of one is
    an error - callers record a `None` result as a missing field.
    """
    for selector in selectors:
        element = tree.select_one(selector)
        if element is not None:
            return ResolvedField(element.get_text(" ", strip=True), selector)
    return ResolvedField(None, None)
