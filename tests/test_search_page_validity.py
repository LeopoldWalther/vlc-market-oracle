"""Tests for search-page validity: telling a block, a genuine no-results answer and a real
page apart, plus the page cap.
"""

import pathlib
import unittest
from datetime import datetime, timezone

from src.idealista.models import SearchTarget
from src.idealista.search_page_parser import SearchPageRejected, parse_search_page

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
OBSERVED_AT = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

RENT_TARGET = SearchTarget(
    municipality="l-eliana",
    district=None,
    operation="rent",
    base_url="https://www.idealista.com/alquiler-viviendas/l-eliana-valencia/",
    expected_listings=42,
)
SORTED_PAGE_URL = (
    "https://www.idealista.com/alquiler-viviendas/l-eliana-valencia/"
    "?ordenado-por=fecha-publicacion-desc"
)

# The real ZenRows body for a zero-result search: RESP002 JSON, never HTML. The parser must not
# try to read cards or a result count out of it; status_code alone decides the outcome.
RESP002_BODY = (
    '{"code":"RESP002","detail":"The requested URL page returned a 404 HTTP Status Code. '
    'Please make sure this URL exists and retry your request.","instance":"/v1",'
    '"status":404,"title":"Page not found (RESP002)",'
    '"type":"https://docs.zenrows.com/api-error-codes#RESP002"}'
)


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestLastPageIsValid(unittest.TestCase):
    def test_the_last_page_does_not_raise_and_has_no_next_page_url(self) -> None:
        result = parse_search_page(
            _read_fixture("idealista_search_page_last.html"),
            RENT_TARGET,
            SORTED_PAGE_URL,
            OBSERVED_AT,
        )
        self.assertIsNone(result.next_page_url)
        self.assertEqual(len(result.observations), 3)


class TestChallengeIsRejected(unittest.TestCase):
    def test_the_head_only_challenge_page_raises_search_page_rejected(self) -> None:
        with self.assertRaises(SearchPageRejected) as caught:
            parse_search_page(
                _read_fixture("idealista_search_page_challenge.html"),
                RENT_TARGET,
                SORTED_PAGE_URL,
                OBSERVED_AT,
            )
        self.assertIn(SORTED_PAGE_URL, str(caught.exception))

    def test_a_challenge_is_never_reported_as_an_empty_area(self) -> None:
        # The historical failure mode M4 corrects: a block must not produce a "healthy, zero
        # listing" result, which is indistinguishable from success without inspecting the HTML.
        try:
            parse_search_page(
                _read_fixture("idealista_search_page_challenge.html"),
                RENT_TARGET,
                SORTED_PAGE_URL,
                OBSERVED_AT,
            )
        except SearchPageRejected:
            return
        self.fail("a challenge page must raise SearchPageRejected, not return a result")


class TestZeroCardsWithAResultCountIsValid(unittest.TestCase):
    def test_a_page_with_the_result_count_but_no_cards_is_valid(self) -> None:
        html = """
        <span id="h1-container__text">0 casas y pisos en alquiler en L'Eliana</span>
        <section class="items-container items-list"></section>
        """
        result = parse_search_page(html, RENT_TARGET, SORTED_PAGE_URL, OBSERVED_AT)
        self.assertEqual(result.observations, ())
        self.assertFalse(result.no_results)


class TestNoResultsResponse(unittest.TestCase):
    def test_a_404_response_is_surfaced_as_no_results_not_an_exception(self) -> None:
        result = parse_search_page(
            RESP002_BODY, RENT_TARGET, SORTED_PAGE_URL, OBSERVED_AT, status_code=404
        )
        self.assertTrue(result.no_results)
        self.assertEqual(result.observations, ())
        self.assertIsNone(result.next_page_url)

    def test_no_results_is_distinct_from_a_valid_empty_page(self) -> None:
        valid_empty = parse_search_page(
            "<span id='h1-container__text'>0 casas</span>"
            "<section class='items-container items-list'></section>",
            RENT_TARGET,
            SORTED_PAGE_URL,
            OBSERVED_AT,
        )
        self.assertFalse(valid_empty.no_results)


class TestCardWithoutAPriceReduction(unittest.TestCase):
    def test_yields_none_for_both_previous_price_and_drop_percentage(self) -> None:
        result = parse_search_page(
            _read_fixture("idealista_search_page.html"), RENT_TARGET, SORTED_PAGE_URL, OBSERVED_AT
        )
        by_id = {o.listing_id: o for o in result.observations}
        card = by_id["112598657"]
        self.assertIsNone(card.prev_price_eur)
        self.assertIsNone(card.price_drop_pct)


class TestPageCap(unittest.TestCase):
    def test_reaching_the_cap_stops_pagination_and_reports_page_cap_reached(self) -> None:
        result = parse_search_page(
            _read_fixture("idealista_search_page.html"),
            RENT_TARGET,
            SORTED_PAGE_URL,
            OBSERVED_AT,
            page_number=3,
            page_cap=3,
        )
        self.assertIsNone(result.next_page_url)
        self.assertTrue(result.page_cap_reached)

    def test_below_the_cap_pagination_continues_normally(self) -> None:
        result = parse_search_page(
            _read_fixture("idealista_search_page.html"),
            RENT_TARGET,
            SORTED_PAGE_URL,
            OBSERVED_AT,
            page_number=2,
            page_cap=3,
        )
        self.assertIsNotNone(result.next_page_url)
        self.assertFalse(result.page_cap_reached)

    def test_the_default_cap_is_60(self) -> None:
        result = parse_search_page(
            _read_fixture("idealista_search_page.html"),
            RENT_TARGET,
            SORTED_PAGE_URL,
            OBSERVED_AT,
            page_number=60,
        )
        self.assertIsNone(result.next_page_url)
        self.assertTrue(result.page_cap_reached)


if __name__ == "__main__":
    unittest.main()
