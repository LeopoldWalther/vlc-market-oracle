import asyncio
import json
import os
import random
import re
import secrets
import string
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import unquote

import nest_asyncio
from browserforge.headers import HeaderGenerator
from patchright.async_api import async_playwright

nest_asyncio.apply()

# ---------------------------------------------------------------------------
# Dataclass Definition
# ---------------------------------------------------------------------------

@dataclass
class PropertyListing:
    url: str
    idealista_id: str
    
    price_eur: Optional[int] = None
    prev_price_eur: Optional[int] = None
    price_drop_pct: Optional[float] = None
    price_per_sqm: Optional[float] = None
    community_fee_eur_month: Optional[int] = None
    
    sqm_built: Optional[int] = None
    sqm_usable: Optional[int] = None
    
    rooms: Optional[int] = None
    bathrooms: Optional[int] = None
    floor: Optional[str] = None
    is_exterior: Optional[bool] = None
    orientation: list[str] = field(default_factory=list)
    has_elevator: bool = False
    has_balcony: bool = False
    has_parking: bool = False
    has_ac: bool = False
    has_fitted_wardrobes: bool = False
    has_heating: Optional[bool] = None
    heating_type: Optional[str] = None
    
    title: str = ""
    location: str = ""
    description: str = ""
    neighborhood: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    year_built: Optional[int] = None
    condition: Optional[str] = None
    
    raw_features: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper Parsing Functions (Pure Logic)
# ---------------------------------------------------------------------------

def _extract_idealista_id_from_url(url: str) -> str:
    match = re.search(r"/inmueble/(\d+)/", url)
    return match.group(1) if match else ""

def _parse_int_from_text(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None

def _parse_pct_from_text(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else None

def _parse_orientations(feature_text: str) -> list[str]:
    directions = ["norte", "sur", "este", "oeste", "noreste", "noroeste", "sureste", "suroeste"]
    found: list[str] = []
    for direction in directions:
        if re.search(rf"\b{direction}\b", feature_text):
            found.append(direction)
    return found

def _parse_coords_from_text(text: str) -> tuple[Optional[float], Optional[float]]:
    center_match = re.search(r"[?&]center=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", text)
    if center_match:
        return float(center_match.group(1)), float(center_match.group(2))

    marker_match = re.search(r"markers=[^&]*?(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", text)
    if marker_match:
        return float(marker_match.group(1)), float(marker_match.group(2))

    latlng_match = re.search(r"LatLng\((-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\)", text)
    if latlng_match:
        return float(latlng_match.group(1)), float(latlng_match.group(2))

    return None, None

def parse_features(raw_features: list[str]) -> dict:
    result = {
        "sqm_built": None, "sqm_usable": None, "rooms": None, "bathrooms": None,
        "floor": None, "is_exterior": None, "orientation": [], "year_built": None,
        "condition": None, "has_balcony": False, "has_elevator": False,
        "has_ac": False, "has_fitted_wardrobes": False, "has_parking": False,
        "has_heating": None, "heating_type": None,
    }

    for feature in raw_features:
        f = feature.lower().strip()

        m = re.search(r"(\d+)\s*m²\s*construidos", f)
        if m: result["sqm_built"] = int(m.group(1))

        m = re.search(r"(\d+)\s*m²\s*[uú]tiles", f)
        if m: result["sqm_usable"] = int(m.group(1))

        m = re.search(r"(\d+)\s*habitacion", f)
        if m: result["rooms"] = int(m.group(1))

        m = re.search(r"(\d+)\s*ba[ñn]", f)
        if m: result["bathrooms"] = int(m.group(1))

        m = re.search(r"(\d+)[aª°]?\s*planta", f)
        if m: result["floor"] = m.group(1)

        if "exterior" in f: result["is_exterior"] = True
        elif "interior" in f and result["is_exterior"] is None: result["is_exterior"] = False

        m = re.search(r"construido en\s*(\d{4})", f)
        if m: result["year_built"] = int(m.group(1))

        if "para reformar" in f: result["condition"] = "needs_renovation"
        elif "buen estado" in f or "segunda mano" in f: result["condition"] = "good"
        elif "obra nueva" in f or "nuevo" in f: result["condition"] = "new"

        if "balc" in f: result["has_balcony"] = True
        if "ascensor" in f: result["has_elevator"] = True
        if "aire acondicionado" in f: result["has_ac"] = True
        if "armarios empotrados" in f: result["has_fitted_wardrobes"] = True
        if "garaje" in f or "parking" in f: result["has_parking"] = True

        if "no dispone de calefacci" in f or "sin calefacci" in f:
            result["has_heating"] = False
            result["heating_type"] = None
        elif "calefacci" in f:
            if result["has_heating"] is None: result["has_heating"] = True
            if "gas natural" in f: result["heating_type"] = "natural gas"

        if "orientaci" in f:
            parsed_orientations = _parse_orientations(f)
            if parsed_orientations: result["orientation"] = parsed_orientations

    return result


# ---------------------------------------------------------------------------
# Async Playwright Extraction Functions
# ---------------------------------------------------------------------------

async def _extract_community_fee_eur_month(page) -> int | None:
    rows = await page.locator("//section[contains(@class, 'price-features__container')]//p[contains(@class, 'flex-feature')]").all()
    for row in rows:
        # Hier die ungültigen .// XPath Ausdrücke durch saubere CSS-Selektoren ersetzen:
        label_el = row.locator("span.flex-feature-text")
        detail_el = row.locator("span.flex-feature-details")
        
        if await label_el.count() > 0 and await detail_el.count() > 0:
            label = (await label_el.first.inner_text()).lower().strip()
            if "gastos de comunidad" in label:
                return _parse_int_from_text(await detail_el.first.inner_text())
    return None

async def _extract_location_parts(page) -> tuple[Optional[str], Optional[str], Optional[str]]:
    rows = await page.locator("//div[@id='headerMap']//li[contains(@class, 'header-map-list')]").all()
    texts = [(await row.inner_text()).strip() for row in rows if (await row.inner_text()).strip()]

    neighborhood: Optional[str] = None
    district: Optional[str] = None
    city: Optional[str] = None

    for text in texts:
        lower_text = text.lower()
        if lower_text.startswith("barrio "):
            neighborhood = text.split(" ", 1)[1].strip()
        elif lower_text.startswith("distrito "):
            district = text.split(" ", 1)[1].strip()
        elif lower_text.startswith("valencia"):
            city = "Valencia"

    if city is None and texts:
        city = texts[-1].split(",")[0].strip()

    return neighborhood, district, city

async def _extract_coordinates(page) -> tuple[Optional[float], Optional[float]]:
    url_candidates: list[str] = []

    map_images = await page.locator("//div[@id='map']//img[contains(@src, 'staticmap')] | //img[@id='sMap']").all()
    for img in map_images:
        src = await img.get_attribute("src") or ""
        if src:
            url_candidates.append(src)

    show_map_links = await page.locator("//a[contains(@class, 'showMap')]").all()
    for link in show_map_links:
        href = await link.get_attribute("href") or ""
        if href:
            url_candidates.append(href)

    for candidate in url_candidates:
        lat, lon = _parse_coords_from_text(unquote(candidate))
        if lat is not None and lon is not None:
            return lat, lon

    page_source = await page.content()
    lat, lon = _parse_coords_from_text(unquote(page_source))
    if lat is not None and lon is not None:
        return lat, lon

    return None, None

async def _expand_description(page) -> None:
    toggles = await page.locator(
        "//div[contains(@class, 'adCommentsLanguage')]"
        "//*[contains(@class, 'expandable') or contains(@class, 'see-more') "
        "or contains(@class, 'link-underline') or contains(text(), 'Ver más') "
        "or contains(text(), 'más')]"
    ).all()
    for toggle in toggles:
        try:
            await toggle.click(force=True, timeout=1000)
            await asyncio.sleep(random.uniform(0.3, 0.6))
        except Exception:
            continue

async def _extract_description(page) -> str:
    await _expand_description(page)
    comment_elements = await page.locator("//div[contains(@class, 'adCommentsLanguage')]//p").all()
    parts = [(await element.inner_text()).strip() for element in comment_elements if (await element.inner_text()).strip()]
    return "\n\n".join(parts)

async def extract_property_details(page, property_url: str) -> PropertyListing:
    # CSS-Selektoren anstelle von ungültigem .// XPath nutzen
    title_el = page.locator('span.main-info__title-main')
    title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else ""
    
    description = await _extract_description(page)
    
    location_el = page.locator('span.main-info__title-minor')
    location = (await location_el.inner_text()).strip() if await location_el.count() > 0 else ""

    neighborhood, district, city = await _extract_location_parts(page)
    latitude, longitude = await _extract_coordinates(page)
    
    price_el = page.locator('span.info-data-price')
    price_text = (await price_el.inner_text()).strip() if await price_el.count() > 0 else ""

    prev_price_el = page.locator('span.pricedown_price')
    prev_price_text = (await prev_price_el.inner_text()).strip() if await prev_price_el.count() > 0 else None

    price_drop_el = page.locator('span.pricedown_icon')
    price_drop_text = (await price_drop_el.inner_text()).strip() if await price_drop_el.count() > 0 else None

    # XPath explizit mit // starten
    feature_items = await page.locator("//div[contains(@class, 'details-property_features')]//li").all()
    raw_features = [(await li.inner_text()).strip() for li in feature_items if (await li.inner_text()).strip()]
    
    features = parse_features(raw_features)

    price_eur = _parse_int_from_text(price_text)
    sqm_built = features["sqm_built"]
    price_per_sqm = (price_eur / sqm_built) if price_eur and sqm_built else None

    listing = PropertyListing(
        url=property_url,
        idealista_id=_extract_idealista_id_from_url(property_url),
        price_eur=price_eur,
        prev_price_eur=_parse_int_from_text(prev_price_text),
        price_drop_pct=_parse_pct_from_text(price_drop_text),
        price_per_sqm=price_per_sqm,
        community_fee_eur_month=await _extract_community_fee_eur_month(page),
        sqm_built=features["sqm_built"],
        sqm_usable=features["sqm_usable"],
        rooms=features["rooms"],
        bathrooms=features["bathrooms"],
        floor=features["floor"],
        is_exterior=features["is_exterior"],
        orientation=features["orientation"],
        has_elevator=features["has_elevator"],
        has_balcony=features["has_balcony"],
        has_parking=features["has_parking"],
        has_ac=features["has_ac"],
        has_fitted_wardrobes=features["has_fitted_wardrobes"],
        has_heating=features["has_heating"],
        heating_type=features["heating_type"],
        title=title,
        description=description,
        location=location,
        neighborhood=neighborhood,
        district=district,
        city=city,
        latitude=latitude,
        longitude=longitude,
        year_built=features["year_built"],
        condition=features["condition"],
        raw_features=raw_features,
    )
    return listing


# ---------------------------------------------------------------------------
# Proxy Configuration (IProyal residential, sticky session)
# ---------------------------------------------------------------------------

USE_PROXY = True

IPROYAL_HOST = "geo.iproyal.com"
IPROYAL_PORT = 12321


def build_iproyal_proxy_config(
    username: str,
    password: str,
    country: str = "es",
    lifetime_minutes: int = 15,
    host: str = IPROYAL_HOST,
    port: int = IPROYAL_PORT,
) -> dict[str, str]:
    """Build a Playwright proxy config with a fresh IProyal sticky session.

    IProyal expects targeting parameters appended to the password, not the username.
    Each call generates a new session id, which maps to a new exit IP.
    killswitch-1 aborts the request instead of falling back to the real IP.
    """
    session_id = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8)
    )
    return {
        "server": f"http://{host}:{port}",
        "username": username,
        "password": (
            f"{password}_country-{country}_session-{session_id}"
            f"_lifetime-{lifetime_minutes}m_killswitch-1"
        ),
    }


def load_iproyal_credentials() -> tuple[str, str]:
    """Read IProyal credentials from the environment."""
    username = os.environ.get("IPROYAL_USERNAME")
    password = os.environ.get("IPROYAL_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "IPROYAL_USERNAME and IPROYAL_PASSWORD must be set in the environment."
        )
    return username, password


# ---------------------------------------------------------------------------
# Main Execution Pipeline
# ---------------------------------------------------------------------------

async def main():
    target_url = "https://www.idealista.com/inmueble/106749418/"
    
    headers_gen = HeaderGenerator(browser="chrome", os="windows", device="desktop")
    custom_headers = headers_gen.generate()
    user_agent = custom_headers.get("user-agent")

    proxy_config = None
    if USE_PROXY:
        proxy_username, proxy_password = load_iproyal_credentials()
        proxy_config = build_iproyal_proxy_config(proxy_username, proxy_password)
        print(f"Proxy aktiv: {proxy_config['server']}")
    else:
        print("Proxy deaktiviert, direkte Verbindung.")

    async with async_playwright() as p:
        # Chromium ignores context-level proxies unless the browser launches with one.
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            proxy={"server": "per-context"} if USE_PROXY else None,
        )

        context = await browser.new_context(
            user_agent=user_agent,
            extra_http_headers=custom_headers,
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport={"width": 1920, "height": 1080},
            proxy=proxy_config
        )

        page = await context.new_page()

        print("1. Lade Startseite (Warm-up für DataDome Session)...")
        await page.goto("https://www.idealista.com/", wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(2, 3))

        cookie_btn = page.locator("#didomi-notice-agree-button")
        if await cookie_btn.is_visible(timeout=3000):
            await cookie_btn.click()
            await asyncio.sleep(random.uniform(1, 2))

        print(f"2. Navigiere zum Inserat {target_url}...")
        response = await page.goto(target_url, wait_until="domcontentloaded")

        if response.status == 200:
            print("3. Extrahiere Inseratsdaten...")
            listing = await extract_property_details(page, target_url)
            
            # Ausgabe des Dataclass-Dictionarys
            listing_dict = asdict(listing)
            print("\nErfolgreich geparstes Listing:")
            print(json.dumps(listing_dict, indent=2, ensure_ascii=False))
        else:
            print(f"Fehler beim Aufrufen der Seite. Status Code: {response.status}")

        await context.close()
        await browser.close()

asyncio.run(main())