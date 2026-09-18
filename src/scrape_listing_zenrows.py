"""Fetch one Idealista listing through ZenRows and print the parsed snapshot.

Exploration entry point. Usage:

    python -m src.scrape_listing_zenrows https://www.idealista.com/inmueble/106749418/
"""

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.idealista.listing_parser import parse_listing_html
from src.idealista.zenrows_source import fetch_listing_html, load_zenrows_api_key

RAW_HTML_DIR = Path(__file__).parents[1] / "data" / "raw" / "idealista"


def save_raw_html(html: str, idealista_id: str, observed_at: datetime) -> Path:
    """Persist the raw payload so parsing stays replayable without re-fetching."""
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = observed_at.strftime("%Y%m%dT%H%M%SZ")
    path = RAW_HTML_DIR / f"{idealista_id}_{timestamp}.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("listing_url")
    parser.add_argument(
        "--no-js-render",
        action="store_true",
        help="Skip headless rendering (cheaper, but usually blocked).",
    )
    parser.add_argument(
        "--no-premium-proxy",
        action="store_true",
        help="Skip residential proxies (cheaper, but usually blocked).",
    )
    args = parser.parse_args()

    load_dotenv()
    api_key = load_zenrows_api_key(os.environ)

    observed_at = datetime.now(timezone.utc)
    html = fetch_listing_html(
        args.listing_url,
        api_key,
        js_render=not args.no_js_render,
        premium_proxy=not args.no_premium_proxy,
    )

    listing = parse_listing_html(html, args.listing_url)
    raw_path = save_raw_html(html, listing.idealista_id or "unknown", observed_at)

    snapshot = asdict(listing) | {"observed_at": observed_at.isoformat()}
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"\nRaw HTML: {raw_path}")


if __name__ == "__main__":
    main()
