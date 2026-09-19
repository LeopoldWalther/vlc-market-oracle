"""Tests for replaying a crawl from stored raw HTML."""

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from src.idealista.cached_fetcher import (
    CachedHtmlFetcher,
    MissingRawPayload,
    raw_html_path,
)
from src.idealista.models import HtmlFetcher

SEARCH_URL = "https://www.idealista.com/alquiler-viviendas/l-eliana-valencia/"
OTHER_URL = "https://www.idealista.com/venta-viviendas/l-eliana-valencia/"


class _CachedFetcherTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raw_root = Path(self._tmp.name)

    def store(self, url: str, html: str, observed_at: datetime) -> Path:
        path = raw_html_path(self.raw_root, url, observed_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return path


class TestCachedHtmlFetcher(_CachedFetcherTestCase):
    def test_it_satisfies_the_html_fetcher_protocol(self) -> None:
        self.assertIsInstance(CachedHtmlFetcher(self.raw_root), HtmlFetcher)

    def test_a_stored_payload_is_replayed_verbatim_at_zero_cost(self) -> None:
        self.store(
            SEARCH_URL,
            "<html>page one</html>",
            datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc),
        )
        fetcher = CachedHtmlFetcher(self.raw_root)

        outcome = fetcher.fetch(SEARCH_URL)

        self.assertEqual(outcome.html, "<html>page one</html>")
        self.assertEqual(outcome.status_code, 200)
        self.assertEqual(outcome.credits_spent, 0)
        self.assertEqual(fetcher.credits_spent, 0)
        self.assertEqual(fetcher.requests, 1)

    def test_a_replay_opens_no_network_connection(self) -> None:
        self.store(
            SEARCH_URL, "<html>ok</html>", datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc)
        )
        fetcher = CachedHtmlFetcher(self.raw_root)

        with mock.patch(
            "socket.socket", side_effect=AssertionError("the replay opened a socket")
        ):
            outcome = fetcher.fetch(SEARCH_URL)

        self.assertEqual(outcome.html, "<html>ok</html>")

    def test_the_most_recent_payload_wins_when_several_timestamps_exist(self) -> None:
        self.store(
            SEARCH_URL, "<html>older</html>", datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc)
        )
        self.store(
            SEARCH_URL, "<html>newest</html>", datetime(2026, 2, 11, 7, 30, tzinfo=timezone.utc)
        )
        self.store(
            SEARCH_URL, "<html>middle</html>", datetime(2026, 2, 10, 18, 0, tzinfo=timezone.utc)
        )

        outcome = CachedHtmlFetcher(self.raw_root).fetch(SEARCH_URL)

        self.assertEqual(outcome.html, "<html>newest</html>")

    def test_payloads_of_other_urls_are_never_returned(self) -> None:
        self.store(
            OTHER_URL, "<html>sale</html>", datetime(2026, 2, 11, 9, 0, tzinfo=timezone.utc)
        )
        self.store(
            SEARCH_URL, "<html>rent</html>", datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc)
        )

        outcome = CachedHtmlFetcher(self.raw_root).fetch(SEARCH_URL)

        self.assertEqual(outcome.html, "<html>rent</html>")

    def test_a_url_without_a_stored_payload_raises_an_error_naming_it(self) -> None:
        fetcher = CachedHtmlFetcher(self.raw_root)

        with self.assertRaises(MissingRawPayload) as error:
            fetcher.fetch(SEARCH_URL)

        self.assertIn(SEARCH_URL, str(error.exception))
        self.assertEqual(error.exception.url, SEARCH_URL)

    def test_a_missing_raw_directory_raises_the_same_specific_error(self) -> None:
        fetcher = CachedHtmlFetcher(self.raw_root / "never-written")

        with self.assertRaises(MissingRawPayload):
            fetcher.fetch(SEARCH_URL)


class TestRawHtmlPath(_CachedFetcherTestCase):
    def test_the_path_partitions_by_the_utc_observation_date(self) -> None:
        path = raw_html_path(
            self.raw_root, SEARCH_URL, datetime(2026, 2, 11, 7, 30, tzinfo=timezone.utc)
        )

        self.assertEqual(path.parent.name, "observed_date=2026-02-11")
        self.assertTrue(path.name.endswith("__20260211T073000Z.html"))

    def test_the_file_name_stays_readable_and_url_specific(self) -> None:
        search = raw_html_path(
            self.raw_root, SEARCH_URL, datetime(2026, 2, 11, 7, 30, tzinfo=timezone.utc)
        )
        other = raw_html_path(
            self.raw_root, OTHER_URL, datetime(2026, 2, 11, 7, 30, tzinfo=timezone.utc)
        )

        self.assertIn("alquiler-viviendas-l-eliana-valencia", search.name)
        self.assertNotEqual(search.name, other.name)

    def test_a_naive_observation_time_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            raw_html_path(self.raw_root, SEARCH_URL, datetime(2026, 2, 11, 7, 30))


if __name__ == "__main__":
    unittest.main()
