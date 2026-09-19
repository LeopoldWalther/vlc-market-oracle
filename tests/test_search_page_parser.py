"""Tests for turning one Idealista search page into listing observations."""

import pathlib
import unittest
from datetime import datetime, timezone

from src.idealista.models import SearchTarget
from src.idealista.search_page_parser import parse_search_page

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


def _parse_fixture(name: str, page_url: str = SORTED_PAGE_URL):
    html = (FIXTURES / name).read_text(encoding="utf-8")
    return parse_search_page(html, RENT_TARGET, page_url, OBSERVED_AT)


class TestParseSearchPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = _parse_fixture("idealista_search_page.html")

    def test_every_card_yields_one_observation(self) -> None:
        self.assertEqual(len(self.result.observations), 4)
        self.assertEqual(
            [o.listing_id for o in self.result.observations],
            ["112497875", "112598657", "112593408", "112592240"],
        )

    def test_listing_id_matches_the_id_in_the_item_link_href(self) -> None:
        for observation in self.result.observations:
            self.assertEqual(
                observation.listing_url,
                f"https://www.idealista.com/inmueble/{observation.listing_id}/",
            )
        self.assertEqual(self.result.drift, ())

    def test_prices_and_sizes_are_parsed_as_ints(self) -> None:
        first = self.result.observations[0]
        self.assertEqual(first.price_eur, 3_000)
        self.assertEqual(first.prev_price_eur, 3_200)
        self.assertEqual(first.price_drop_pct, 6.0)
        self.assertEqual(first.sqm_built, 200)
        self.assertEqual(first.rooms, 4)

    def test_a_leading_non_numeric_feature_does_not_shift_rooms_or_size(self) -> None:
        # Card 1 reads "Garaje incluido | 4 hab. | 200 m2"; card 2 has no leading feature.
        by_id = {o.listing_id: o for o in self.result.observations}
        self.assertEqual((by_id["112497875"].rooms, by_id["112497875"].sqm_built), (4, 200))
        self.assertEqual((by_id["112598657"].rooms, by_id["112598657"].sqm_built), (1, 81))

    def test_a_floor_description_containing_digits_is_not_read_as_rooms_or_size(self) -> None:
        # Card 3 also carries "1a planta exterior con ascensor" and "22 horas".
        card = {o.listing_id: o for o in self.result.observations}["112593408"]
        self.assertEqual((card.rooms, card.sqm_built), (1, 60))

    def test_a_card_without_a_price_reduction_has_no_previous_price(self) -> None:
        card = {o.listing_id: o for o in self.result.observations}["112598657"]
        self.assertIsNone(card.prev_price_eur)
        self.assertIsNone(card.price_drop_pct)

    def test_freshness_badge_is_captured_verbatim_or_left_none(self) -> None:
        by_id = {o.listing_id: o for o in self.result.observations}
        self.assertEqual(by_id["112598657"].freshness_label, "7 horas")
        self.assertEqual(by_id["112593408"].freshness_label, "22 horas")
        self.assertIsNone(by_id["112497875"].freshness_label)

    def test_observations_carry_the_target_and_the_injected_clock(self) -> None:
        first = self.result.observations[0]
        self.assertEqual(first.operation, "rent")
        self.assertEqual(first.municipality, "l-eliana")
        self.assertEqual(first.observed_at, OBSERVED_AT)

    def test_result_count_comes_from_the_page_header(self) -> None:
        self.assertEqual(self.result.result_count, 42)

    def test_next_page_url_is_absolute_and_keeps_the_sort_query(self) -> None:
        self.assertEqual(
            self.result.next_page_url,
            "https://www.idealista.com/alquiler-viviendas/l-eliana-valencia/"
            "pagina-2.htm?ordenado-por=fecha-publicacion-desc",
        )


class TestNextPageUrl(unittest.TestCase):
    def test_the_sort_query_is_re_applied_when_the_next_href_drops_it(self) -> None:
        # Measured in task 0.3: with the bare ?fecha-publicacion-desc form the site emits a
        # next href without any query, which would silently return page 2 in relevance order.
        html = """
        <span id="h1-container__text">42 casas</span>
        <section class="items-container items-list"></section>
        <div class="pagination"><ul><li class="next">
          <a href="/alquiler-viviendas/l-eliana-valencia/pagina-2.htm"></a>
        </li></ul></div>
        """
        result = parse_search_page(
            html,
            RENT_TARGET,
            "https://www.idealista.com/alquiler-viviendas/l-eliana-valencia/?fecha-publicacion-desc",
            OBSERVED_AT,
        )
        self.assertEqual(
            result.next_page_url,
            "https://www.idealista.com/alquiler-viviendas/l-eliana-valencia/"
            "pagina-2.htm?fecha-publicacion-desc",
        )

    def test_the_last_page_has_no_next_page_url(self) -> None:
        result = _parse_fixture("idealista_search_page_last.html")
        self.assertIsNone(result.next_page_url)
        self.assertEqual(len(result.observations), 3)


class TestIdDrift(unittest.TestCase):
    def test_a_mismatch_between_the_two_id_sources_is_reported_as_drift(self) -> None:
        html = """
        <span id="h1-container__text">42 casas</span>
        <section class="items-container items-list">
          <article class="item" data-element-id="111111111">
            <div class="item-info-container">
              <a class="item-link" href="/inmueble/999999999/"></a>
              <div class="price-row"><span class="item-price">950 <span>€/mes</span></span></div>
              <div class="item-detail-char"><span class="item-detail">1 hab.</span></div>
            </div>
          </article>
        </section>
        """
        result = parse_search_page(html, RENT_TARGET, SORTED_PAGE_URL, OBSERVED_AT)

        self.assertEqual(len(result.drift), 1)
        self.assertIn("111111111", result.drift[0])
        self.assertIn("999999999", result.drift[0])
        # The record is still produced; drift is reported, not silently resolved either way.
        self.assertEqual(len(result.observations), 1)


if __name__ == "__main__":
    unittest.main()
