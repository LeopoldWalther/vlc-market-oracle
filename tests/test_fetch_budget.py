"""Tests for the fetcher protocol, credit accounting, the run budget and retries."""

import unittest

from src.idealista.models import FetchOutcome, HtmlFetcher
from src.idealista.zenrows_source import (
    CREDITS_PLAIN_REQUEST,
    CREDITS_RENDERED_REQUEST,
    CreditBudgetExhausted,
    ZenRowsFetcher,
    ZenRowsFetchError,
)

API_KEY = "test-api-key"
SEARCH_URL = "https://www.idealista.com/alquiler-viviendas/l-eliana-valencia/"
RESP001_BODY = '{"code":"RESP001","detail":"Could not get content."}'
RESP002_BODY = '{"code":"RESP002","detail":"Content not found."}'


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _ScriptedGet:
    """Returns queued responses in order and records every call."""

    def __init__(self, *responses: _FakeResponse) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, url, *, params, timeout):
        self.calls.append(params["url"])
        if not self._responses:
            raise AssertionError("the fetcher issued more requests than scripted")
        return self._responses.pop(0)


class _RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _ok(body: str = "<html>ok</html>") -> _FakeResponse:
    return _FakeResponse(200, body)


def _build_fetcher(
    http_get: _ScriptedGet,
    *,
    sleep: _RecordingSleep | None = None,
    **kwargs,
) -> ZenRowsFetcher:
    return ZenRowsFetcher(
        API_KEY,
        http_get=http_get,
        sleep=sleep or _RecordingSleep(),
        random_unit=lambda: 1.0,
        **kwargs,
    )


class TestFetcherProtocol(unittest.TestCase):
    def test_the_zenrows_fetcher_satisfies_the_html_fetcher_protocol(self) -> None:
        fetcher = _build_fetcher(_ScriptedGet(), credit_budget=100)

        self.assertIsInstance(fetcher, HtmlFetcher)

    def test_a_successful_fetch_returns_the_html_and_its_credit_cost(self) -> None:
        fetcher = _build_fetcher(_ScriptedGet(_ok()), credit_budget=100)

        outcome = fetcher.fetch(SEARCH_URL)

        self.assertEqual(
            outcome,
            FetchOutcome(
                url=SEARCH_URL,
                status_code=200,
                html="<html>ok</html>",
                credits_spent=CREDITS_RENDERED_REQUEST,
            ),
        )


class TestCreditAccounting(unittest.TestCase):
    def test_a_rendered_request_costs_twenty_five_credits(self) -> None:
        fetcher = _build_fetcher(_ScriptedGet(_ok(), _ok()), credit_budget=100)

        fetcher.fetch(SEARCH_URL)
        fetcher.fetch(SEARCH_URL)

        self.assertEqual(fetcher.cost_per_request, 25)
        self.assertEqual(fetcher.credits_spent, 50)
        self.assertEqual(fetcher.requests, 2)

    def test_an_unrendered_request_costs_ten_credits(self) -> None:
        fetcher = _build_fetcher(
            _ScriptedGet(_ok()), credit_budget=100, js_render=False
        )

        fetcher.fetch(SEARCH_URL)

        self.assertEqual(fetcher.cost_per_request, CREDITS_PLAIN_REQUEST)
        self.assertEqual(fetcher.credits_spent, 10)

    def test_a_failed_request_is_billed_at_zero_credits(self) -> None:
        """ZenRows reports X-Request-Cost 0 for every non-200 response."""
        http_get = _ScriptedGet(_FakeResponse(403, "forbidden"))
        fetcher = _build_fetcher(http_get, credit_budget=100)

        with self.assertRaises(ZenRowsFetchError):
            fetcher.fetch(SEARCH_URL)

        self.assertEqual(fetcher.credits_spent, 0)


class TestRunBudget(unittest.TestCase):
    def test_a_budget_permits_exactly_budget_divided_by_cost_requests(self) -> None:
        http_get = _ScriptedGet(_ok(), _ok(), _ok())
        fetcher = _build_fetcher(http_get, credit_budget=80)

        for _ in range(3):
            fetcher.fetch(SEARCH_URL)

        with self.assertRaises(CreditBudgetExhausted):
            fetcher.fetch(SEARCH_URL)

        self.assertEqual(fetcher.requests, 3)
        self.assertEqual(fetcher.credits_spent, 75)

    def test_the_stop_is_controlled_and_names_the_run_budget(self) -> None:
        fetcher = _build_fetcher(_ScriptedGet(_ok()), credit_budget=25)

        fetcher.fetch(SEARCH_URL)
        with self.assertRaises(CreditBudgetExhausted) as stop:
            fetcher.fetch(SEARCH_URL)

        self.assertEqual(stop.exception.reason, "credit_budget_exhausted")
        self.assertEqual(fetcher.stopped_reason, "credit_budget_exhausted")
        self.assertEqual(fetcher.credits_remaining, 0)

    def test_the_stop_reason_is_configurable_for_the_monthly_quota(self) -> None:
        fetcher = _build_fetcher(
            _ScriptedGet(),
            credit_budget=0,
            budget_reason="monthly_budget_exhausted",
        )

        with self.assertRaises(CreditBudgetExhausted) as stop:
            fetcher.fetch(SEARCH_URL)

        self.assertEqual(stop.exception.reason, "monthly_budget_exhausted")
        self.assertEqual(fetcher.stopped_reason, "monthly_budget_exhausted")

    def test_no_request_is_issued_once_the_budget_is_exhausted(self) -> None:
        http_get = _ScriptedGet(_ok())
        fetcher = _build_fetcher(http_get, credit_budget=25)

        fetcher.fetch(SEARCH_URL)
        with self.assertRaises(CreditBudgetExhausted):
            fetcher.fetch(SEARCH_URL)

        self.assertEqual(len(http_get.calls), 1)


class TestRetryClassification(unittest.TestCase):
    def test_a_rate_limit_is_retried_until_it_succeeds(self) -> None:
        http_get = _ScriptedGet(_FakeResponse(429, "slow down"), _ok())
        fetcher = _build_fetcher(http_get, credit_budget=100)

        outcome = fetcher.fetch(SEARCH_URL)

        self.assertEqual(outcome.status_code, 200)
        self.assertEqual(len(http_get.calls), 2)
        self.assertEqual(fetcher.credits_spent, CREDITS_RENDERED_REQUEST)

    def test_a_server_error_is_retried(self) -> None:
        http_get = _ScriptedGet(_FakeResponse(503, "unavailable"), _ok())
        fetcher = _build_fetcher(http_get, credit_budget=100)

        self.assertEqual(fetcher.fetch(SEARCH_URL).status_code, 200)
        self.assertEqual(len(http_get.calls), 2)

    def test_a_transient_zenrows_failure_is_retried(self) -> None:
        """422/RESP001 is transient and billed at zero, so retrying is pure upside."""
        http_get = _ScriptedGet(_FakeResponse(422, RESP001_BODY), _ok())
        fetcher = _build_fetcher(http_get, credit_budget=100)

        self.assertEqual(fetcher.fetch(SEARCH_URL).status_code, 200)
        self.assertEqual(len(http_get.calls), 2)

    def test_a_non_transient_422_is_not_retried(self) -> None:
        http_get = _ScriptedGet(_FakeResponse(422, '{"code":"AUTH004"}'))
        fetcher = _build_fetcher(http_get, credit_budget=100)

        with self.assertRaises(ZenRowsFetchError):
            fetcher.fetch(SEARCH_URL)

        self.assertEqual(len(http_get.calls), 1)

    def test_a_not_found_is_reported_as_an_outcome_rather_than_retried(self) -> None:
        """Idealista answers a zero-result search with 404, which is a fact, not a failure."""
        http_get = _ScriptedGet(_FakeResponse(404, RESP002_BODY))
        fetcher = _build_fetcher(http_get, credit_budget=100)

        outcome = fetcher.fetch(SEARCH_URL)

        self.assertEqual(outcome.status_code, 404)
        self.assertEqual(outcome.credits_spent, 0)
        self.assertEqual(len(http_get.calls), 1)
        self.assertEqual(fetcher.credits_spent, 0)

    def test_a_client_error_other_than_429_is_not_retried(self) -> None:
        http_get = _ScriptedGet(_FakeResponse(401, "unauthorized"))
        fetcher = _build_fetcher(http_get, credit_budget=100)

        with self.assertRaises(ZenRowsFetchError):
            fetcher.fetch(SEARCH_URL)

        self.assertEqual(len(http_get.calls), 1)

    def test_retries_are_bounded_and_the_last_failure_is_raised(self) -> None:
        http_get = _ScriptedGet(*(_FakeResponse(503, "unavailable") for _ in range(3)))
        fetcher = _build_fetcher(http_get, credit_budget=100, max_attempts=3)

        with self.assertRaises(ZenRowsFetchError) as error:
            fetcher.fetch(SEARCH_URL)

        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(len(http_get.calls), 3)


class TestPacing(unittest.TestCase):
    def test_backoff_grows_and_stays_within_the_jitter_window(self) -> None:
        http_get = _ScriptedGet(
            _FakeResponse(503, ""), _FakeResponse(503, ""), _ok()
        )
        sleep = _RecordingSleep()
        fetcher = ZenRowsFetcher(
            API_KEY,
            http_get=http_get,
            sleep=sleep,
            random_unit=lambda: 0.0,
            credit_budget=100,
            pause_seconds=0.0,
            backoff_seconds=2.0,
        )

        fetcher.fetch(SEARCH_URL)

        # random_unit 0.0 is the lower edge of the +-50 % jitter window around 2 s and 4 s.
        self.assertEqual(sleep.delays, [1.0, 2.0])

    def test_requests_are_paced_sequentially_without_pausing_before_the_first(
        self,
    ) -> None:
        http_get = _ScriptedGet(_ok(), _ok())
        sleep = _RecordingSleep()
        fetcher = _build_fetcher(
            http_get, sleep=sleep, credit_budget=100, pause_seconds=1.5
        )

        fetcher.fetch(SEARCH_URL)
        fetcher.fetch(SEARCH_URL)

        self.assertEqual(sleep.delays, [1.5])


if __name__ == "__main__":
    unittest.main()
