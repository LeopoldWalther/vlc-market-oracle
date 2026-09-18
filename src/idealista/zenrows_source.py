"""ZenRows source adapter: fetches raw Idealista HTML through the ZenRows API.

Kept free of parsing logic so the deterministic parser can be tested from fixtures.
"""

from typing import Callable, Mapping, Protocol

ZENROWS_ENDPOINT = "https://api.zenrows.com/v1/"
DEFAULT_TIMEOUT_SECONDS = 180.0


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
