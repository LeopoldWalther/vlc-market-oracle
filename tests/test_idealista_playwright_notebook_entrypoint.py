"""Static checks for the Jupyter-compatible Playwright notebook entry point."""

import ast
import json
import unittest
from pathlib import Path


NOTEBOOK_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "notebooks"
    / "idealista_playwright_scraper.ipynb"
)


class TestPlaywrightNotebookEntrypoint(unittest.TestCase):
    def _scraper_source(self) -> str:
        notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
        return next(
            "".join(cell["source"])
            for cell in notebook["cells"]
            if "async def scrape_idealista_listing" in "".join(cell["source"])
        )

    def _all_code_source(self) -> str:
        notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
        return "\n".join(
            "".join(cell["source"])
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        )

    def test_uses_top_level_await_instead_of_asyncio_run(self) -> None:
        source = self._scraper_source()

        self.assertNotIn("asyncio.run(", source)
        self.assertIn("await scrape_idealista_listing(LISTING_URL)", source)
        compile(source, str(NOTEBOOK_PATH), "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)

    def test_example_url_is_a_plain_https_listing_url(self) -> None:
        source = self._scraper_source()

        self.assertIn(
            'LISTING_URL = "https://www.idealista.com/inmueble/106749418/"',
            source,
        )
        self.assertNotIn("[https://", source)

    def test_uses_real_chrome_without_fingerprint_spoofing(self) -> None:
        source = self._scraper_source()
        normalized = " ".join(source.split())

        self.assertIn(
            '.chromium.launch(channel="chrome", headless=False)',
            normalized,
        )
        for artificial_signal in (
            "ignore_default_args",
            "--disable-blink-features=AutomationControlled",
            "add_init_script",
            "user_agent=",
            "Sec-Ch-Ua",
            "Sec-Fetch-",
            "Windows NT",
            "Direct3D11",
            "navigator.webdriver",
        ):
            with self.subTest(artificial_signal=artificial_signal):
                self.assertNotIn(artificial_signal, source)

    def test_notebook_has_no_captcha_solver_or_nested_event_loop(self) -> None:
        source = self._all_code_source()

        for prohibited_code in (
            "asyncio.run(",
            "CAPSOLVER_API_KEY",
            "api.capsolver.com",
            "AntiTurnstileTaskProxyLess",
            "captcha_token",
            "cf-turnstile-response",
            "from playwright.sync_api import sync_playwright",
        ):
            with self.subTest(prohibited_code=prohibited_code):
                self.assertNotIn(prohibited_code, source)


if __name__ == "__main__":
    unittest.main()