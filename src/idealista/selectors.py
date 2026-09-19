"""An ordered selector registry: each field maps to CSS selectors tried in order.

The mechanism is deliberately dumb: a layout change becomes a data edit to a selector list, not a
code change to a parser. Operates on an already-parsed tree; no network, no filesystem.
"""

from typing import NamedTuple, Optional, Sequence

from bs4 import Tag

SelectorRegistry = dict[str, list[str]]

# Detail-page fields. The second entry of each list is a deliberate structural fallback: it survives
# a renamed class, which is the most common form of Idealista drift.
DETAIL_PAGE: SelectorRegistry = {
    # [class*='info-data-price'] must not be widened to [class*='price'], which would also match
    # pricedown_price and silently read the previous price as the current one.
    "price_eur": [".info-data-price", "[class*='info-data-price']"],
    "prev_price_eur": [".pricedown_price", "[class*='pricedown_price']"],
    "price_drop_pct": [".pricedown_icon", "[class*='pricedown_icon']"],
    "title": [".main-info__title-main", "[class*='title-main']"],
    "location": [".main-info__title-minor", "[class*='title-minor']"],
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
