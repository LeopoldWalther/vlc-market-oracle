"""ZenRows source adapter: fetches raw Idealista HTML through the ZenRows API.

Kept free of parsing logic so the deterministic parser can be tested from fixtures.
"""

import random
import time
from typing import Callable, Mapping, Protocol

from .models import FetchOutcome

ZENROWS_ENDPOINT = "https://api.zenrows.com/v1/"
DEFAULT_TIMEOUT_SECONDS = 180.0

# Idealista is Datadome-protected, so every request needs the premium proxy. Measured against the
# live API: a rendered request costs 25 credits, an unrendered one 10, and any non-200 response is
# billed at zero (``X-Request-Cost: 0``).
CREDITS_RENDERED_REQUEST = 25
CREDITS_PLAIN_REQUEST = 10

CREDIT_BUDGET_EXHAUSTED = "credit_budget_exhausted"

# 422/RESP001 means ZenRows itself could not obtain the page. It is transient and billed at zero,
# so retrying costs nothing. Every other 422 is a configuration or account problem that a retry
# cannot fix. 404/RESP002 is a genuine zero-result search and must never be retried.
_TRANSIENT_ZENROWS_CODE = "RESP001"
_NO_RESULTS_STATUS = 404
_RATE_LIMITED_STATUS = 429
_MAX_BACKOFF_SECONDS = 30.0


class _Response(Protocol):
    status_code: int
    text: str


HttpGet = Callable[..., _Response]


class ZenRowsFetchError(RuntimeError):
    """Raised when ZenRows does not return a successful response."""

    def __init__(self, status_code: int, listing_url: str, body_excerpt: str) -> None:
        super().__init__(
            f"ZenRows returned HTTP {status_code} for {listing_url}: {body_excerpt}"
        )
        self.status_code = status_code
        self.listing_url = listing_url
        self.body_excerpt = body_excerpt


class CreditBudgetExhausted(Exception):
    """Raised instead of spending a credit the run is no longer allowed to spend.

    This is a controlled stop, not a failure: the caller ends the run and writes a partial report.
    """

    def __init__(self, reason: str, credits_spent: int, credit_budget: int) -> None:
        super().__init__(
            f"{reason}: spent {credits_spent} of {credit_budget} credits"
        )
        self.reason = reason
        self.credits_spent = credits_spent
        self.credit_budget = credit_budget


def load_zenrows_api_key(environment: Mapping[str, str]) -> str:
    """Read the ZenRows API key from a mapping such as ``os.environ``."""
    api_key = environment.get("ZENROWS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ZENROWS_API_KEY is not set. Add it to your environment or .env file."
        )
    return api_key


def build_zenrows_params(
    api_key: str,
    listing_url: str,
    *,
    js_render: bool = True,
    premium_proxy: bool = True,
    proxy_country: str = "es",
) -> dict[str, str]:
    """Build the ZenRows query parameters for one listing request.

    ZenRows only accepts ``proxy_country`` together with ``premium_proxy``.
    """
    params = {"apikey": api_key, "url": listing_url}
    if js_render:
        params["js_render"] = "true"
    if premium_proxy:
        params["premium_proxy"] = "true"
        params["proxy_country"] = proxy_country
    return params


def fetch_listing_html(
    listing_url: str,
    api_key: str,
    *,
    http_get: HttpGet | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    js_render: bool = True,
    premium_proxy: bool = True,
    proxy_country: str = "es",
) -> str:
    """Return the rendered HTML of ``listing_url`` as delivered by ZenRows."""
    if http_get is None:
        import requests

        http_get = requests.get

    params = build_zenrows_params(
        api_key,
        listing_url,
        js_render=js_render,
        premium_proxy=premium_proxy,
        proxy_country=proxy_country,
    )
    response = http_get(ZENROWS_ENDPOINT, params=params, timeout=timeout)

    if response.status_code != 200:
        raise ZenRowsFetchError(
            response.status_code, listing_url, response.text[:200]
        )
    return response.text


def _is_retryable(error: ZenRowsFetchError) -> bool:
    """Decide whether repeating the identical request could plausibly succeed."""
    status = error.status_code
    if status == _RATE_LIMITED_STATUS or 500 <= status < 600:
        return True
    if status == 422:
        return _TRANSIENT_ZENROWS_CODE in error.body_excerpt
    return False


class ZenRowsFetcher:
    """A budgeted, sequential ``HtmlFetcher`` backed by the ZenRows API.

    Requests are issued one at a time with a configurable pause: the free allowance is far smaller
    than the concurrency limit, so throughput is not the binding constraint and a thread pool would
    only add ways to overspend. The fetcher refuses to start a request it cannot pay for, which
    makes a budget overrun impossible rather than merely detectable afterwards.
    """

    def __init__(
        self,
        api_key: str,
        *,
        credit_budget: int,
        budget_reason: str = CREDIT_BUDGET_EXHAUSTED,
        js_render: bool = True,
        premium_proxy: bool = True,
        proxy_country: str = "es",
        pause_seconds: float = 1.0,
        max_attempts: int = 3,
        backoff_seconds: float = 2.0,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_unit: Callable[[], float] = random.random,
    ) -> None:
        if credit_budget < 0:
            raise ValueError(f"credit_budget must not be negative, got {credit_budget}")
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")

        self._api_key = api_key
        self._credit_budget = credit_budget
        self._budget_reason = budget_reason
        self._js_render = js_render
        self._premium_proxy = premium_proxy
        self._proxy_country = proxy_country
        self._pause_seconds = pause_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._timeout = timeout
        self._http_get = http_get
        self._sleep = sleep
        self._random_unit = random_unit

        self.requests = 0
        self.credits_spent = 0
        self.stopped_reason: str | None = None

    @property
    def cost_per_request(self) -> int:
        return CREDITS_RENDERED_REQUEST if self._js_render else CREDITS_PLAIN_REQUEST

    @property
    def credits_remaining(self) -> int:
        return self._credit_budget - self.credits_spent

    def fetch(self, url: str) -> FetchOutcome:
        """Return the HTML for ``url``, or stop the run rather than exceed the budget."""
        cost = self.cost_per_request
        if self.credits_spent + cost > self._credit_budget:
            self.stopped_reason = self._budget_reason
            raise CreditBudgetExhausted(
                self._budget_reason, self.credits_spent, self._credit_budget
            )

        if self.requests:
            self._sleep(self._pause_seconds)
        return self._fetch_with_retries(url, cost)

    def _fetch_with_retries(self, url: str, cost: int) -> FetchOutcome:
        attempt = 1
        while True:
            self.requests += 1
            try:
                html = fetch_listing_html(
                    url,
                    self._api_key,
                    http_get=self._http_get,
                    timeout=self._timeout,
                    js_render=self._js_render,
                    premium_proxy=self._premium_proxy,
                    proxy_country=self._proxy_country,
                )
            except ZenRowsFetchError as error:
                if error.status_code == _NO_RESULTS_STATUS:
                    # A zero-result search, not a transport failure. Billed at zero.
                    return FetchOutcome(
                        url=url,
                        status_code=_NO_RESULTS_STATUS,
                        html=error.body_excerpt,
                        credits_spent=0,
                    )
                if attempt >= self._max_attempts or not _is_retryable(error):
                    raise
                self._sleep(self._backoff_delay(attempt))
                attempt += 1
                continue

            self.credits_spent += cost
            return FetchOutcome(
                url=url, status_code=200, html=html, credits_spent=cost
            )

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff capped and spread over a +-50 % jitter window."""
        base = min(self._backoff_seconds * 2 ** (attempt - 1), _MAX_BACKOFF_SECONDS)
        return base * (0.5 + 0.5 * self._random_unit())
