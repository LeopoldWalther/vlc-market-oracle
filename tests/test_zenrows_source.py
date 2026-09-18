"""Tests for the ZenRows source adapter."""

import unittest

from src.idealista.zenrows_source import (
    ZenRowsFetchError,
    build_zenrows_params,
    fetch_listing_html,
    load_zenrows_api_key,
)

API_KEY = "test-api-key"
LISTING_URL = "https://www.idealista.com/inmueble/106749418/"


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _RecordingGet:
    """Stands in for requests.get and records the last call."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.url: str | None = None
        self.params: dict[str, str] | None = None
        self.timeout: float | None = None

    def __call__(self, url, *, params, timeout):
        self.url = url
        self.params = params
        self.timeout = timeout
        return self._response


class TestBuildZenRowsParams(unittest.TestCase):
    def test_defaults_request_rendered_spanish_residential_traffic(self) -> None:
        params = build_zenrows_params(API_KEY, LISTING_URL)

        self.assertEqual(
            params,
            {
                "apikey": API_KEY,
                "url": LISTING_URL,
                "js_render": "true",
                "premium_proxy": "true",
                "proxy_country": "es",
            },
        )

    def test_rendering_and_proxy_can_be_disabled(self) -> None:
        params = build_zenrows_params(
            API_KEY, LISTING_URL, js_render=False, premium_proxy=False
        )

        self.assertNotIn("js_render", params)
        self.assertNotIn("premium_proxy", params)
        self.assertNotIn("proxy_country", params)


class TestFetchListingHtml(unittest.TestCase):
    def test_successful_response_returns_html(self) -> None:
        http_get = _RecordingGet(_FakeResponse(200, "<html>ok</html>"))

        html = fetch_listing_html(LISTING_URL, API_KEY, http_get=http_get, timeout=30)

        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(http_get.url, "https://api.zenrows.com/v1/")
        self.assertEqual(http_get.params["url"], LISTING_URL)
        self.assertEqual(http_get.timeout, 30)

    def test_failed_response_raises_with_status_but_without_the_api_key(self) -> None:
        http_get = _RecordingGet(_FakeResponse(422, "quota exceeded"))

        with self.assertRaises(ZenRowsFetchError) as error:
            fetch_listing_html(LISTING_URL, API_KEY, http_get=http_get)

        message = str(error.exception)
        self.assertIn("422", message)
        self.assertIn(LISTING_URL, message)
        self.assertNotIn(API_KEY, message)
        self.assertEqual(error.exception.status_code, 422)


class TestLoadZenRowsApiKey(unittest.TestCase):
    def test_reads_the_key_from_the_environment(self) -> None:
        self.assertEqual(load_zenrows_api_key({"ZENROWS_API_KEY": API_KEY}), API_KEY)

    def test_missing_key_raises_an_actionable_error(self) -> None:
        with self.assertRaises(RuntimeError) as error:
            load_zenrows_api_key({})

        self.assertIn("ZENROWS_API_KEY", str(error.exception))


if __name__ == "__main__":
    unittest.main()
