"""Offline contract tests for the Playwright Stealth notebook."""

import ast
import asyncio
import io
import json
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from playwright.async_api import Error as PlaywrightError, async_playwright


NOTEBOOK_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "notebooks"
    / "idealista_playwright_scraper.ipynb"
)

EXPECTED_FIELDS = [
    "url",
    "idealista_id",
    "price_eur",
    "prev_price_eur",
    "price_drop_pct",
    "price_per_sqm",
    "community_fee_eur_month",
    "sqm_built",
    "sqm_usable",
    "rooms",
    "bathrooms",
    "floor",
    "is_exterior",
    "orientation",
    "has_elevator",
    "has_balcony",
    "has_parking",
    "has_ac",
    "has_fitted_wardrobes",
    "has_heating",
    "heating_type",
    "title",
    "location",
    "description",
    "neighborhood",
    "district",
    "city",
    "latitude",
    "longitude",
    "year_built",
    "condition",
    "raw_features",
]

LISTING_HTML = """
<!doctype html>
<html lang="es">
  <body>
    <span class="main-info__title-main">Piso luminoso en Valencia</span>
    <span class="main-info__title-minor">Russafa, València</span>
    <span class="info-data-price">250.000 €</span>
    <span class="pricedown_price">275.000 €</span>
    <span class="pricedown_icon">-9,1 %</span>

    <section class="price-features__container">
      <p class="flex-feature">
        <span class="flex-feature-text">Gastos de comunidad</span>
        <span class="flex-feature-details">45 €/mes</span>
      </p>
    </section>

    <div id="headerMap">
      <ul>
        <li class="header-map-list">Barrio Russafa</li>
        <li class="header-map-list">Distrito L'Eixample</li>
        <li class="header-map-list">Valencia, València</li>
      </ul>
    </div>

    <div class="details-property_features">
      <ul>
        <li>100 m² construidos</li>
        <li>90 m² útiles</li>
        <li>3 habitaciones</li>
        <li>2 baños</li>
        <li>4ª planta exterior con ascensor</li>
        <li>Construido en 1985, segunda mano/buen estado</li>
        <li>Orientación norte, este</li>
        <li>Balcón, garaje, aire acondicionado y armarios empotrados</li>
        <li>Calefacción individual: gas natural</li>
      </ul>
    </div>

    <div class="adCommentsLanguage">
      <p>Primera parte.</p>
      <p>Segunda parte.</p>
    </div>

    <div id="map">
      <img src="https://maps.example/staticmap?center=39.4621%2C-0.3768&amp;zoom=15">
    </div>
  </body>
</html>
"""


def _load_definition_namespace() -> dict[str, object]:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        assert cell["metadata"]["language"] == (
            "python" if cell["cell_type"] == "code" else "markdown"
        )

    namespace: dict[str, object] = {}
    definition_cells = [
        cell
        for cell in notebook["cells"]
      if "# notebook-test: definitions" in "".join(cell["source"])
    ]
    if not definition_cells:
      raise AssertionError("Notebook must contain marked definition cells")

    for cell in definition_cells:
        exec("".join(cell["source"]), namespace)
    return namespace


class TestPlaywrightStealthNotebook(unittest.TestCase):
    """Verify the notebook's stable output contract without live requests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.namespace = _load_definition_namespace()

    def test_listing_dataclass_has_same_fields_as_selenium_notebook(self) -> None:
        listing_type = self.namespace["PropertyListing"]
        self.assertEqual(list(listing_type.__dataclass_fields__), EXPECTED_FIELDS)

    def test_rejects_urls_outside_the_single_listing_boundary(self) -> None:
      with self.assertRaises(ValueError):
        self.namespace["_validate_property_url"]("https://example.com/inmueble/1/")

    def test_aborts_when_a_captcha_is_present(self) -> None:
      async def check_challenge():
        async with async_playwright() as playwright:
          browser = await playwright.chromium.launch()
          try:
            page = await browser.new_page()
            await page.set_content('<div id="captcha">Verify you are human</div>')
            await self.namespace["_raise_if_access_is_blocked"](page)
          finally:
            await browser.close()

      listing_error = self.namespace["ListingExtractionError"]
      with self.assertRaisesRegex(listing_error, "do not attempt to bypass"):
        asyncio.run(check_challenge())

    def test_stealth_configuration_masks_webdriver_flag(self) -> None:
      async def webdriver_status() -> bool:
        stealth = self.namespace["_create_stealth"]()
        async with stealth.use_async(async_playwright()) as playwright:
          browser = await playwright.chromium.launch()
          try:
            page = await browser.new_page()
            return await page.evaluate("navigator.webdriver")
          finally:
            await browser.close()

      self.assertFalse(asyncio.run(webdriver_status()))

    def test_http_403_does_not_claim_an_unproven_cause(self) -> None:
      listing_error = self.namespace["ListingExtractionError"]
      with self.assertRaisesRegex(
        listing_error,
      "HTTP 403.*cause is not determined",
      ):
        self.namespace["_raise_for_http_status"](403)

    def _fake_scrape(self, *, status=403, body="Access denied: captcha datadome",
             body_error=None, navigation_error=None, redirects=False):
      """Exercise the real orchestration with a fully fake browser/network boundary."""
      frame = object()
      request = SimpleNamespace(
        is_navigation_request=lambda: True,
        frame=frame,
        headers={"user-agent": "TestBrowser/151", "accept-language": "es-ES",
             "cookie": "COOKIE_SECRET", "authorization": "AUTH_SECRET"},
      )
      response = SimpleNamespace(
        status=status,
        url="https://www.idealista.com/inmueble/106749418/?token=QUERY_SECRET#FRAGMENT_SECRET",
        request=request,
        headers={"content-type": "text/html; charset=utf-8", "server": "test-server",
             "x-request-id": "request-123", "set-cookie": "COOKIE_SECRET",
             "x-datadome": "PROVIDER_TOKEN", "location": "/login?token=LOCATION_SECRET"},
        text=AsyncMock(return_value=body, side_effect=body_error),
      )
      page = SimpleNamespace(
        main_frame=frame, url=response.url, on=Mock(),
        locator=Mock(),
      )

      async def goto(*args, **kwargs):
        callback = page.on.call_args.args[1]
        if redirects:
          callback(SimpleNamespace(
            status=302, url="https://www.idealista.com/inmueble/106749418/",
            request=request, headers={"location": response.url},
          ))
        if navigation_error is not None:
          raise navigation_error
        callback(response)
        return response

      page.goto = AsyncMock(side_effect=goto)
      page.locator.return_value.first.wait_for = AsyncMock()
      context = SimpleNamespace(new_page=AsyncMock(return_value=page))
      browser = SimpleNamespace(
        version="151.0.test", new_context=AsyncMock(return_value=context),
        close=AsyncMock(),
      )
      playwright = SimpleNamespace(chromium=SimpleNamespace(
        launch=AsyncMock(return_value=browser)))

      @asynccontextmanager
      async def manager():
        yield playwright

      stealth = SimpleNamespace(use_async=lambda _: manager())
      diagnostics = []
      extract = AsyncMock(return_value="listing-result")
      caught = None
      result = None
      with patch.dict(self.namespace, {
        "_create_stealth": lambda: stealth,
        "async_playwright": lambda: None,
        "_raise_if_access_is_blocked": AsyncMock(),
        "extract_property_details": extract,
      }):
        try:
          result = asyncio.run(self.namespace["scrape_property_url"](
            "https://www.idealista.com/inmueble/106749418/",
            diagnostics=diagnostics,
          ))
        except self.namespace["ListingExtractionError"] as error:
          caught = error
      browser.close.assert_awaited_once()
      page.goto.assert_awaited_once()
      return diagnostics, caught, result, extract

    def test_403_diagnostics_survive_browser_close_without_secrets(self) -> None:
      reports, error, result, extract = self._fake_scrape(redirects=True)
      self.assertIsNotNone(error)
      self.assertIsNone(result)
      extract.assert_not_awaited()
      self.assertEqual(len(reports), 1)
      report = asdict(reports[0])
      self.assertEqual(report["stage"], "http_status")
      self.assertEqual(report["browser_version"], "151.0.test")
      self.assertFalse(report["headless"])
      self.assertIsNotNone(datetime.fromisoformat(report["captured_at"]).tzinfo)
      self.assertGreaterEqual(report["elapsed_ms"], 0)
      self.assertEqual([item["status"] for item in report["responses"]], [302, 403])
      final = report["responses"][-1]
      self.assertEqual(final["url"], "https://www.idealista.com/inmueble/106749418/")
      self.assertEqual(final["response_headers"]["x-request-id"], "request-123")
      self.assertEqual(final["request_headers"]["user-agent"], "TestBrowser/151")
      self.assertIn("x-datadome", final["provider_header_names"])
      self.assertIn("captcha", report["body_signals"])
      self.assertIn("datadome", report["body_signals"])
      serialized = json.dumps(report)
      for secret in ("COOKIE_SECRET", "AUTH_SECRET", "QUERY_SECRET", "FRAGMENT_SECRET",
               "PROVIDER_TOKEN", "LOCATION_SECRET", "Access denied: captcha datadome"):
        self.assertNotIn(secret, serialized)

    def test_body_read_failure_preserves_http_error_and_diagnostics(self) -> None:
      for body_error in (PlaywrightError("BODY_SECRET"), TimeoutError("BODY_SECRET")):
        with self.subTest(error=type(body_error).__name__):
          reports, error, _, _ = self._fake_scrape(body_error=body_error)
          self.assertIn("HTTP 403", str(error))
          self.assertEqual(reports[0].body_read_error, type(body_error).__name__)
          self.assertEqual(reports[0].body_signals, ())
          self.assertNotIn("BODY_SECRET", json.dumps(asdict(reports[0])))

    def test_navigation_failure_without_response_is_reported_safely(self) -> None:
      reports, error, _, extract = self._fake_scrape(
        navigation_error=PlaywrightError("URL_WITH_SECRET net::ERR_NAME_NOT_RESOLVED"))
      self.assertEqual(reports[0].stage, "navigation")
      self.assertEqual(reports[0].responses, ())
      self.assertEqual(reports[0].network_error, "net::ERR_NAME_NOT_RESOLVED")
      self.assertNotIn("URL_WITH_SECRET", str(error) + json.dumps(asdict(reports[0])))
      extract.assert_not_awaited()

    def test_success_keeps_listing_contract_and_records_status(self) -> None:
      reports, error, result, extract = self._fake_scrape(status=200, body="Listing text")
      self.assertIsNone(error)
      self.assertEqual(result, "listing-result")
      extract.assert_awaited_once()
      self.assertEqual(reports[0].stage, "complete")
      self.assertEqual(reports[0].responses[-1].status, 200)

    def test_diagnostic_url_drops_credentials_queries_and_unknown_paths(self) -> None:
      sanitize = self.namespace["_diagnostic_url"]
      self.assertEqual(
        sanitize("https://USER:PASS@example.com/reset/PATH_SECRET?token=QUERY_SECRET#FRAGMENT_SECRET"),
        "https://example.com/<redacted-path>",
      )
      self.assertEqual(sanitize("data:text/html,SECRET"), "<redacted-url>")

    def test_diagnostics_on_intercepted_response_without_external_network(self) -> None:
      async def collect():
        async with async_playwright() as playwright:
          browser = await playwright.chromium.launch()
          try:
            context = await browser.new_context(service_workers="block")
            await context.route("**/*", lambda route: route.fulfill(
              status=403, content_type="text/html",
              body="<html><body>Verify you are human: captcha</body></html>",
            ))
            page = await context.new_page()
            response = await page.goto("https://diagnostic.invalid/inmueble/1/")
            return await self.namespace["_response_body_signals"](response)
          finally:
            await browser.close()

      signals, truncated, error = asyncio.run(collect())
      self.assertIn("captcha", signals)
      self.assertIn("verify you are human", signals)
      self.assertFalse(truncated)
      self.assertIsNone(error)

    def test_live_cell_prints_diagnostics_even_after_failure(self) -> None:
      reports, _, _, _ = self._fake_scrape()

      async def failed_scrape(url, *, headless, diagnostics):
        diagnostics.extend(reports)
        raise self.namespace["ListingExtractionError"]("HTTP 403")

      notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
      source = "".join(notebook["cells"][9]["source"])
      namespace = dict(self.namespace, RUN_LIVE=True, HEADLESS=False,
               PROPERTY_URL="https://www.idealista.com/inmueble/106749418/",
               scrape_property_url=failed_scrape, live_result="stale listing",
               diagnostic_report={"stale": True})
      output = io.StringIO()
      with redirect_stdout(output):
        asyncio.run(eval(compile(source, str(NOTEBOOK_PATH), "exec",
                     flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), namespace))
      self.assertIsNone(namespace["live_result"])
      self.assertEqual(namespace["diagnostic_report"]["stage"], "http_status")
      self.assertIn('"status": 403', output.getvalue())
      self.assertNotIn("stale", output.getvalue())

      namespace["RUN_LIVE"] = False
      with redirect_stdout(io.StringIO()):
        asyncio.run(eval(compile(source, str(NOTEBOOK_PATH), "exec",
                     flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), namespace))
      self.assertIsNone(namespace["diagnostic_report"])
      self.assertEqual(namespace["live_diagnostics"], [])

    def test_offline_notebook_cell_blocks_all_resource_requests(self) -> None:
      notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
      source = "".join(notebook["cells"][6]["source"]).split("offline_listing =", 1)[0]
      namespace = dict(self.namespace)
      exec(source, namespace)
      page = SimpleNamespace(route=AsyncMock(), set_content=AsyncMock())
      browser = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock())

      @asynccontextmanager
      async def manager():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))

      with patch.dict(namespace, {"async_playwright": manager,
                    "extract_property_details": AsyncMock()}):
        asyncio.run(namespace["run_offline_validation"]())
      page.route.assert_awaited_once()
      self.assertEqual(page.route.call_args.args[0], "**/*")
      route = SimpleNamespace(abort=AsyncMock())
      asyncio.run(page.route.call_args.args[1](route))
      route.abort.assert_awaited_once()
      browser.close.assert_awaited_once()

    def test_extracts_listing_from_local_html(self) -> None:
        async def extract_listing():
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                try:
                    page = await browser.new_page()
                    await page.route("**/*", lambda route: route.abort())
                    await page.set_content(LISTING_HTML)
                    return await self.namespace["extract_property_details"](
                        page,
                        "https://www.idealista.com/inmueble/106749418/",
                    )
                finally:
                    await browser.close()

        result = asdict(asyncio.run(extract_listing()))

        self.assertEqual(list(result), EXPECTED_FIELDS)
        self.assertEqual(result["idealista_id"], "106749418")
        self.assertEqual(result["price_eur"], 250_000)
        self.assertEqual(result["prev_price_eur"], 275_000)
        self.assertEqual(result["price_drop_pct"], -9.1)
        self.assertEqual(result["price_per_sqm"], 2_500.0)
        self.assertEqual(result["community_fee_eur_month"], 45)
        self.assertEqual(result["sqm_built"], 100)
        self.assertEqual(result["sqm_usable"], 90)
        self.assertEqual(result["rooms"], 3)
        self.assertEqual(result["bathrooms"], 2)
        self.assertEqual(result["floor"], "4")
        self.assertTrue(result["is_exterior"])
        self.assertEqual(result["orientation"], ["norte", "este"])
        self.assertTrue(result["has_elevator"])
        self.assertTrue(result["has_balcony"])
        self.assertTrue(result["has_parking"])
        self.assertTrue(result["has_ac"])
        self.assertTrue(result["has_fitted_wardrobes"])
        self.assertTrue(result["has_heating"])
        self.assertEqual(result["heating_type"], "natural gas")
        self.assertEqual(result["title"], "Piso luminoso en Valencia")
        self.assertEqual(result["location"], "Russafa, València")
        self.assertEqual(result["description"], "Primera parte.\n\nSegunda parte.")
        self.assertEqual(result["neighborhood"], "Russafa")
        self.assertEqual(result["district"], "L'Eixample")
        self.assertEqual(result["city"], "Valencia")
        self.assertEqual(result["latitude"], 39.4621)
        self.assertEqual(result["longitude"], -0.3768)
        self.assertEqual(result["year_built"], 1985)
        self.assertEqual(result["condition"], "good")


if __name__ == "__main__":
    unittest.main()