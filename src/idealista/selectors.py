"""An ordered selector registry: each field maps to CSS selectors tried in order.

The mechanism is deliberately dumb: a layout change becomes a data edit to a selector list, not a
code change to a parser. Operates on an already-parsed tree; no network, no filesystem.
"""

from typing import NamedTuple, Optional, Sequence

from bs4 import Tag

SelectorRegistry = dict[str, list[str]]


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
