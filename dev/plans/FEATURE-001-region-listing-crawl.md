# FEATURE-001 — Region-wide Idealista collection with drift-resistant extraction

**Status:** 🟡 In progress · **Effort:** L (~12h) · **Priority:** High
**Branch root:** `feature/region-listing-crawl` · **Created:** 2026-09-18 · **Updated:** 2026-09-18

> Authored by `@architect`. Reviewed by `@reviewer` (see `dev/reviews/REVIEW-FEATURE-001.md`).
> Implemented by `@implementer` from `dev/plans/technical/FEATURE-001-technical-plan.yaml`.

## Objective

Collect every listing URL of a configured set of search areas (initially L'Eliana only, sale and
rent) by paginating the search results, and turn them into two datasets — a narrow weekly
observation series per listing and a one-off full detail record — so that an Idealista layout change
fails visibly instead of silently producing wrong data, and so that a local test run can be limited
to a small subset.

## Context

- **Current state:**
  - [src/idealista/zenrows_source.py](../../src/idealista/zenrows_source.py) fetches the HTML of a
    single URL through ZenRows (`apikey`, `js_render`, `premium_proxy`, `proxy_country`).
  - [src/idealista/listing_parser.py](../../src/idealista/listing_parser.py) parses a detail page
    into a `PropertyListing` using fixed CSS selectors.
  - [src/scrape_listing_zenrows.py](../../src/scrape_listing_zenrows.py) is a CLI for **one** URL
    and stores the raw HTML under `data/raw/idealista/`.
  - Verified on 2026-09-18 against `https://www.idealista.com/inmueble/106749418/`: 24 of 30 fields
    populated, raw HTML 206 KB.
- **Problem:**
  1. There is no path from a search area to listing URLs; every URL must be supplied by hand.
  2. Extraction depends on individual CSS classes (`.info-data-price`, `.main-info__title-main`,
     …). If Idealista renames a class the parser returns `None` instead of failing, so the data
     would be silently incomplete. Verified: the detail page contains **no** JSON-LD, no
     `utag_data` and no `__NEXT_DATA__`, so there is no structured alternative to selectors.
  3. A run across thousands of listings is neither locally testable nor affordable without a
     subset mode.
- **Constraints:**
  - Every ZenRows request costs credits: 25 with `js_render` + `premium_proxy`, 10 with
    `premium_proxy` only. Credits are the dominant cost factor of the whole project.
  - **The ZenRows plan is Free: 5,000 credits per month, monthly refresh, no rollover, 5 concurrent
    requests.** The user will not upgrade before the pipeline is proven, so the starting scope and
    the backfill must fit inside 5,000 credits per month. This is the binding constraint of this
    feature.
  - Collection rules from `.github/copilot-instructions.md`: publicly reachable pages only,
    throttled load, replayable raw payloads, no personal data in logs or fixtures.

## Confirmed Idealista facts

Observed by the user on 2026-09-18 in the browser and its element inspector. These are evidence, not
assumptions, and the selector registry starts from them.

- A search results page shows exactly **30 cards**; pagination is capped at **60 pages**, so one
  search yields at most **1,800 listings**. Idealista states this explicitly on the last page
  ("¿Has visto 1.800 viviendas y aún no encuentras lo que buscas?").
- Consequence: all of Valencia city cannot be collected from one search. The expansion path is
  neighbourhood URLs of the form
  `https://www.idealista.com/venta-viviendas/valencia/<district>/<neighbourhood>/`, for example
  `.../valencia/extramurs/arrancapins/`. Note this differs from the municipality form
  `.../venta-viviendas/valencia-valencia/`.
- Page URLs follow `<search-url>/pagina-<n>.htm`.
- Cards live in `section.items-container.items-list`; each card is an
  `article.item` carrying the listing id directly in **`data-element-id`**. That attribute is a far
  more stable id source than parsing the href, and becomes the primary selector.
- Pagination lives in `div.pagination > ul`; the next page is `li.next > a[href]` with a relative
  href such as `/venta-viviendas/valencia-valencia/pagina-48.htm`.
- A card already carries: current price, the **previous price struck through**, the **price drop
  percentage**, rooms (`2 hab.`), size (`97 m²`), and a floor/exterior/elevator phrase
  (`Entreplanta exterior sin ascensor`), plus a description snippet and the agency.
- The search page also shows an average price per m² for the area.

## Scope

- **In scope:** search page parsing including pagination, a selector registry with fallbacks,
  per-field coverage and drift reporting, quarantine for implausible pages, crawl orchestration with
  subset, replay and cards-only modes, an enforced credit budget, a CLI and configurable search
  targets. Results are written **locally** under `data/`. Also: removal of the superseded browser
  notebooks.
- **Starting scope:** two search targets — L'Eliana sale and L'Eliana rent. Estimated ~360 listings
  and ~12 search pages per pass. Small enough to prove the pipeline inside the Free plan.
- **Out of scope:** Valencia neighbourhoods (added afterwards as configuration lines, one
  neighbourhood at a time), S3 persistence (FEATURE-002), container and scheduling (FEATURE-003),
  Silver/Gold, Iceberg, time-on-market derivation, image downloads, agent or contact data.
- **Users / consumers:** the developer locally at first; FEATURE-002 as a sink afterwards.

## Decided constraints

Decided on 2026-09-18 together with the user, or autonomously where no answer was available. Every
decision is reversible and states its reason:

1. **Two cadences.** Search pages run weekly; detail pages are fetched only when a new listing id
   appears. A purely monthly run would hide every listing that appears and disappears within a
   month — exactly the signal that carries time-on-market and liquidity. The crawler therefore needs
   a `--cards-only` mode.
2. **Each detail page is fetched exactly once per listing id.** Apart from the price, a listing's
   attributes do not change, and the price is already on the card — including the previous price and
   the drop percentage. After the initial backfill the crawler therefore only fetches detail pages
   for ids it has never seen. This is the single largest cost saving in the design: steady-state
   detail traffic drops to the rate of genuinely new listings.
3. **An enforced credit budget instead of an estimate.** The run stops in a controlled way once a
   configured budget is reached and writes a partial report. With a 5,000-credit monthly allowance
   and no rollover, this is what keeps a mistake from consuming a whole month.
4. **Staged initial backfill.** Detail pages are fetched by priority (newest first) up to the
   budget; the remainder carries over to the next run. At the starting scope this matters directly:
   with `js_render` enabled the backfill does not fit into a single Free month.
5. **`js_render` stays enabled by default** until the validation spike proves otherwise — silent
   data loss costs more than the factor of 2.5 in credits. The spike decides whether the backfill
   takes one month or three.
6. **The Playwright and Selenium notebooks and their tests are removed.** The ZenRows path replaces
   them, their tests have been failing since the last notebook change, and maintaining two parallel
   collection paths contradicts the repository rules.
7. **L'Eliana only to start.** Valencia neighbourhoods are added one at a time after the pipeline is
   proven and only then, if needed, is the ZenRows plan upgraded. Adding an area is a line in
   `config/search_targets.yaml`, not a code change.

## Dependencies

- **Needs:** none — it builds directly on the existing ZenRows path.
- **Unblocks:** FEATURE-002 (needs `ListingObservation` and `ListingDetail` as stable records),
  FEATURE-003 (needs an idempotent, parameterizable batch entry point).

## Validation spike (notebook)

The workflow rules no longer require a notebook. One is still the right form here because the
analysis is iterative and the stored raw HTML is examined repeatedly from different angles.

- **Path:** `src/notebooks/FEATURE-001-search-page-spike.ipynb`
- **Question 1 (the decisive cost lever):** does a search results page fetched through ZenRows
  **without** `js_render` yield the same 30 listing ids as with it? If so, credits per request drop
  from 25 to 10 and the whole backfill fits into a single Free month instead of three. The
  comparison uses the set of `data-element-id` values, not the HTML length — ZenRows can return a
  challenge page with HTTP 200 when blocked.
- **Question 2 (selectors):** do the confirmed selectors hold in the HTML that ZenRows returns, and
  does the card really expose the previous price and drop percentage in a parseable form?
- **Question 3 (volume):** how many listings does L'Eliana actually have per operation? This
  replaces the estimate in this plan and fixes the backfill schedule.

### External cross-check (ScrapingBee article, read 2026-09-18)

The article the user linked was reviewed. It agrees with the confirmed facts above and adds no
requirement, but it raises the confidence in three design decisions:

- **Card and pagination selectors match.** It uses `article` with class `item` for the cards and
  `li.next > a` for the next page — the same structure this plan builds on. It does **not** know
  the `data-element-id` attribute and parses the id out of the link instead, so this plan's primary
  id source is the more robust of the two.
- **No structured data.** The article extracts everything from CSS/XPath selectors and mentions no
  JSON-LD, `__NEXT_DATA__` or `utag_data` either. This independently supports the selector registry
  with fallbacks rather than a search for a hidden JSON payload.
- **Datadome is the anti-bot system, and a premium/residential proxy is the answer.** Its own
  browser route needs a captcha solved by hand at least once per session — exactly the reason this
  plan uses a managed API (ZenRows with `premium_proxy`) instead of Playwright/Selenium.
- **What it does not answer:** whether `js_render` is really needed for the *search* page (its
  browser route renders JavaScript by definition, so it cannot distinguish), nor the 60-page cap.
  Question 1 of the spike therefore stays the decisive one.
- **Method:** 4 targeted live requests (L'Eliana sale page 1 with and without `js_render`, L'Eliana
  sale page 2, L'Eliana rent page 1), store the raw HTML, then analyse strictly offline. The stored
  pages become redacted test fixtures.
- **Cost:** ~4 requests ≤ 100 credits, about 2 % of the monthly allowance.
- **What it does not prove:** nothing about stability over weeks, nothing about detail page
  extraction, nothing about concurrency under load.

## Design

- **Primary approach:** a two-stage crawl that feeds exactly the two requested tables.
  - **Stage 1 — `listing_observation`:** paginates the search pages weekly and produces **one row
    per listing and observation day** (id, url, price, previous price, price drop, m², rooms — all
    already on the card). This is the narrow, dense time series: from "id appears in week N, missing
    from week M" the listing duration and every price change can be derived. Bronze stores only the
    observations; `first_seen`, `last_seen` and `days_on_market` are derived in Silver so that facts
    and derivations stay separate.
  - **Stage 2 — `listing_detail`:** fetches the detail page **once per listing id, for ids not seen
    before**, and provides the full attribute set for deeper analysis. A listing's attributes do not
    change once published; the only moving value is the price, and that is already on the card.
    There is therefore no reason to ever re-fetch a detail page, and no price-change trigger in this
    stage.

  Two consequences worth naming:
  - The known-id set is the crawler's only piece of state. It is rebuilt from the stored
    `listing_detail` records rather than kept in a side file, so a lost local state file cannot
    cause silent gaps or duplicate spending.
  - A listing that is missing in one week and present again in the next must not count as two
    listings for the duration analysis. The observation table therefore deliberately holds raw
    observations only; gap handling is an explicit Silver decision.

- **Boundaries and data flow:**

  ```
  search_targets.yaml
        │
        ▼
  region_crawler ──► zenrows_source ──► raw HTML (always stored first)
        │                                    │
        │                                    ├─► search_page_parser ─► ListingObservation[]
        │                                    └─► listing_parser ─────► ListingDetail
        ▼
  crawl run report (coverage, drift, quarantine, credit usage)
  ```

  Direction: `region_crawler` → `zenrows_source` (protocol `HtmlFetcher`), `region_crawler` →
  parsers (pure functions). The parsers know neither network nor filesystem.

- **Contracts and invariants:**
  - `SearchTarget(municipality, district, operation, base_url)` — configuration, not code.
  - `ListingObservation(listing_id, listing_url, operation, municipality, district, price_eur,
    prev_price_eur, price_drop_pct, sqm_built, rooms, observed_at)` — one row per listing and
    observation.
  - `ListingDetail` = today's `PropertyListing` **plus** `operation`, `municipality`, `district`,
    `observed_at` (UTC), `extraction_version`, `missing_fields`. Written once per `listing_id`.
  - Both records share `listing_id` as the join key between the two tables.
  - **Removed:** `price_per_sqm` leaves Bronze. It is a derived value and, as a `float`,
    incompatible with the repository's money rule; the derivation belongs in Silver.
  - Raw HTML is persisted **before** parsing. Every record is reproducible from the raw HTML.
  - Idempotency: a second run on the same day produces the same records (key = `listing_id` +
    `observed_date`), never duplicates.

- **DOM resilience — four measures that work together:**
  1. **Selector registry with ordered fallbacks** (`selectors.py`): every field is a list of
     candidate selectors and the first match wins. Pure data, testable without network. A layout
     change becomes a one-line data change instead of a code change.
  2. **Field provenance instead of a silent `None`:** the parser reports which selector matched and
     which fields are missing (`missing_fields`).
  3. **Required-field contract plus quarantine:** if `listing_id`, `price_eur` or `sqm_built` is
     missing, no record is written. Raw HTML and diagnostics go to `data/quarantine/`.
  4. **Per-run coverage thresholds:** the report measures the fill rate per field. Falling below a
     configured threshold (for example price < 98 %, rooms < 90 %) ends the run with a non-zero exit
     code and names the affected fields. A fixture corpus of real stored pages serves as the
     regression test; every detected change adds a new fixture.

- **OOP / SOLID:** deliberately few objects. Parsers and selector resolution stay **pure functions**
  (no state, no variants). Objects only where there is a real reason:
  - `HtmlFetcher` as a narrow `Protocol` (DIP/ISP), so crawler tests run without network and
    FEATURE-003 can supply a different implementation;
  - `CachedHtmlFetcher` as a second implementation that reads stored raw HTML instead of calling
    ZenRows (replay and debug mode, 0 credits);
  - value objects (frozen dataclasses) for `SearchTarget`, `ListingObservation`, `ListingDetail`.
  - **No** adapter interface for "more portals" while only Idealista exists. **No** Strategy pattern
    for extraction — the variability lives in data (the selector registry), not in classes. No
    inheritance.
- **Patterns:** *Dependency Injection* at the network boundary (`HtmlFetcher`). Nothing else.
- **Deliberately rejected complexity:** no async/`asyncio` (a thread pool with bounded concurrency
  is enough and easier to test), no Playwright/Patchright in the production path, no custom queue or
  state machine, no ORM or database layer, no generic portal framework.

## Approach

### Phase 0 — Evidence
- [ ] Run the validation spike and answer the three questions (above all the `js_render` on/off
      comparison of extracted `data-element-id` sets); store the search page raw HTML under
      `data/raw/idealista/search/` and adopt it redacted as test fixtures. Result: the `js_render`
      default, confirmed selectors, the real L'Eliana result counts, and therefore the backfill
      schedule.

### Phase 1 — Search page parsing
- [ ] **RED:** `test_search_page_parser.py` against a stored search page fixture expects 30
      `ListingObservation`s carrying id (from `data-element-id`), url, price, previous price, drop
      percentage, m² and rooms, plus the total result count and the next page URL. Expected
      failure: `ModuleNotFoundError`. **GREEN:** `search_page_parser.py`. **REFACTOR:** move the
      selectors into the registry.
- [ ] **RED:** a test for the last page (no "next page") and for a page without results returns
      `next_page_url is None` and an empty observation list without raising. A further case covers
      a card **without** a price reduction, where previous price and drop percentage are `None`.
      **GREEN/REFACTOR.**
- [ ] **RED:** a test for the 60-page cap — pagination stops at the documented maximum and the
      report records `page_cap_reached` for that target, so an area that outgrows a single search
      becomes visible instead of silently truncating. **GREEN/REFACTOR.**

### Phase 2 — Drift-resistant detail extraction
- [ ] **RED:** `test_selectors.py` — `resolve_field` takes an ordered selector list and returns the
      first match plus the name of the matching selector; with no match it returns `None` and adds
      the field name to `missing_fields`. **GREEN:** `selectors.py`. **REFACTOR:** move
      `listing_parser.py` onto the registry; existing tests must stay green.
- [ ] **RED:** a test with a mutated fixture (price class renamed) expects the fallback selector to
      match; a second mutation (all price selectors removed) expects `ListingRejected` naming the
      required field instead of a record. **GREEN/REFACTOR.**
- [ ] **RED:** `test_crawl_report.py` — a list of extraction results produces a report with per-field
      coverage; a breached threshold sets `report.failed = True` and names the fields.
      **GREEN/REFACTOR.**

### Phase 3 — Crawl orchestration
- [ ] **RED:** `test_region_crawler.py` with a `FakeHtmlFetcher` (3 fixture pages) expects
      pagination to the end, deduplicated ids, a stop at `max_pages`, and no requests beyond the
      limit. **GREEN:** `region_crawler.py`. **REFACTOR.**
- [ ] **RED:** a test for incremental selection — given a set of already known listing ids, only
      **unknown** ids are proposed for detail fetching. A known id whose card price changed is
      explicitly **not** re-fetched; the price change is captured by the observation row alone.
      **GREEN/REFACTOR.**
- [ ] **RED:** a test for fault tolerance — a `ZenRowsFetchError` on one of three detail pages does
      not abort the run, increments the error counter in the report, and lets the remaining records
      be produced. Bounded retries with backoff only for 429/5xx. **GREEN/REFACTOR.**
- [ ] **RED:** a test for `CachedHtmlFetcher` — replay from `data/raw/` produces identical records
      without a single network call. **GREEN/REFACTOR.**
- [ ] **RED:** a test for the credit budget — a budget of N credits allows exactly
      `N / cost_per_request` requests, then stops in a controlled way, writes a partial report with
      `stopped_reason = "credit_budget_exhausted"`, and does **not** exit with an error.
      **GREEN/REFACTOR.**
- [ ] **RED:** a test for the staged backfill — given a known backlog and a limited budget, detail
      pages are selected by priority and the remainder is carried over. **GREEN/REFACTOR.**

### Phase 4 — Configuration and CLI
- [ ] **RED:** `test_search_targets.py` — loading `config/search_targets.yaml` yields typed
      `SearchTarget`s; an unknown `operation` or a missing URL raises a specific configuration
      error. **GREEN/REFACTOR.**
- [ ] **RED:** `test_collect_region_cli.py` — argument parsing for `--target`, `--max-pages`,
      `--max-listings`, `--cards-only`, `--credit-budget`, `--replay`, `--no-js-render` and
      `--dry-run`; `--dry-run` provably triggers no fetch. **GREEN:** `src/collect_region.py`.
      **REFACTOR:** fold `scrape_listing_zenrows.py` into the shared path or remove it.
- [ ] Validation: a local run with `--max-pages 1 --max-listings 10` against a small search target
      (L'Eliana); inspect the report and records, then do a replay run that spends no credits.
- [ ] Remove the superseded browser paths: `src/notebooks/idealista_playwright_scraper.ipynb`,
      `src/notebooks/idealista_selenium_scraper.ipynb`, `tests/test_idealista_playwright_*.py`,
      `src/dev_dataclass.py` and the Playwright/Selenium entries in `requirements-notebook.txt`.
      The full suite must be green afterwards.
- [ ] Align the README sections "Current repository state" and "Responsible collection" with the
      new state (today's text still forbids anti-bot mitigation and contradicts
      `.github/copilot-instructions.md`).

## Files

- **Create:**
  - `src/idealista/search_page_parser.py` — search page → `ListingObservation[]`, result count, next
    page.
  - `src/idealista/selectors.py` — selector registry with ordered fallbacks per field.
  - `src/idealista/region_crawler.py` — orchestration, limits, retries, report.
  - `src/idealista/models.py` — `SearchTarget`, `ListingObservation`, `ListingDetail`, `CrawlReport`.
  - `src/idealista/cached_fetcher.py` — replay from stored raw HTML.
  - `src/collect_region.py` — CLI entry point.
  - `config/search_targets.yaml` — search areas; initially L'Eliana venta and alquiler only, with
    a commented Valencia neighbourhood example showing the
    `/venta-viviendas/valencia/<district>/<neighbourhood>/` form for later expansion.
  - `src/notebooks/FEATURE-001-search-page-spike.ipynb`
- **Change:**
  - `src/idealista/listing_parser.py` — move to the selector registry, add `missing_fields`, drop
    `price_per_sqm`, add `operation`, `municipality` and `extraction_version`.
  - `src/idealista/zenrows_source.py` — `HtmlFetcher` protocol, bounded concurrency, retries with
    backoff and jitter for 429/5xx, credit counter and budget stop.
  - `src/scrape_listing_zenrows.py` — fold into the shared path.
  - `requirements.txt` — `PyYAML` for the search target configuration.
  - `README.md` — current state and collection policy sections.
- **Delete:** `src/notebooks/idealista_playwright_scraper.ipynb`,
  `src/notebooks/idealista_selenium_scraper.ipynb`,
  `tests/test_idealista_playwright_notebook_entrypoint.py`,
  `tests/test_idealista_playwright_stealth_notebook.py`, `src/dev_dataclass.py`, and the
  Playwright/Selenium entries in `requirements-notebook.txt`.
- **Tests:** `tests/test_search_page_parser.py`, `tests/test_selectors.py`,
  `tests/test_listing_parser.py` (extended), `tests/test_crawl_report.py`,
  `tests/test_region_crawler.py`, `tests/test_search_targets.py`,
  `tests/test_collect_region_cli.py`, `tests/fixtures/idealista_search_page*.html`,
  `tests/__init__.py` (makes `unittest discover` work again).

## Test strategy

- **Unit:** card extraction, end of pagination, selector fallbacks, required-field rejection,
  coverage thresholds, limit and budget enforcement, retry classification, configuration errors.
- **Contract / fixtures:** real, redacted search and detail pages as fixtures, plus **mutated**
  fixtures (renamed or removed classes) as an explicit drift test case.
- **Integration:** a full crawl through `FakeHtmlFetcher` across several fixture pages, end to end
  up to the `CrawlReport`. No test may call the live portal.
- **Retries / idempotency / evolution:** a second run on the same day produces identical records;
  `extraction_version` changes only on a deliberate parser change.
- **Configured quality checks:** `python -m unittest discover -s tests -t . -v` and
  `python dev/tools/validate_workflow.py`. Two pieces of legacy are cleared in this feature:
  `tests/` gets an `__init__.py` so `unittest discover` runs again, and the failing Playwright
  notebook tests are removed together with their notebooks. The full suite must be green at the end.
- **Manual:** one bounded live run (`--max-pages 1 --max-listings 10`), then a replay run.

## Operational and compliance impact

- **Scraping / legal:** public search and detail pages only. Bounded concurrency (default 5) and a
  configurable pause between requests. Kill switches: `--max-listings` and a credit budget that
  stops the run before the quota is exceeded.
- **Privacy / security:** do not extract agent, contact or user data. The API key comes from the
  environment only and never appears in logs, fixtures or raw HTML file names. Redact fixtures
  before committing.
- **Observability:** the `CrawlReport` as JSON: requests, credits spent, pages per search target,
  records, quarantine, errors by category, coverage per field. Log aggregates only.
- **Failure and recovery:** explicit timeouts; retries only for 429/5xx with backoff and jitter;
  individual failures do not end the run; the raw HTML allows a full replay without spending new
  credits.
- **Migration / compatibility:** `PropertyListing` changes (`price_per_sqm` is dropped, fields are
  added). Since no consumer exists yet, no migration is required — only the local `data/` directory
  is affected.

## Estimated monthly cloud cost

**$0/month — no AWS resources added or changed.** This feature runs entirely locally.

**External / non-AWS cost — ZenRows, the only real cost and the binding constraint.**

Plan in use: **Free — 5,000 credits/month, monthly refresh, no rollover, 5 concurrent requests.**
Idealista is a hard-protected site, which is why a page costs 25 credits with `js_render` and
`premium_proxy`, or 10 with `premium_proxy` alone. The user will not upgrade until the pipeline is
proven, so the plan must fit inside 5,000 credits per month.

Assumptions for L'Eliana, to be replaced by the spike's real numbers: ~300 sale and ~60 rent
listings; 30 cards per page ⇒ 10 + 2 = **12 search pages per pass**; ~25 genuinely new listings per
month.

| Run | Requests / month | @ 25 credits | @ 10 credits (no `js_render`) |
|---|---|---|---|
| Search pages, weekly (4.33 × 12) | ~52 | ~1,300 | ~520 |
| Detail pages, new ids only | ~25 | ~625 | ~250 |
| **Steady state total** | **~77** | **~1,925** | **~770** |
| Initial backfill (360 details, one-off) | 360 | ~9,000 | ~3,600 |
| Validation spike | 4 one-off | ~100 | ~40 |

**Does Free suffice?**

- **Steady state: comfortably yes** — ~1,925 credits is 39 % of the monthly allowance even with
  `js_render` enabled.
- **The backfill is the only tight spot.** With `js_render` it needs 9,000 credits, which does not
  fit in one 5,000-credit month. After the weekly search pages there are ~3,700 credits left, so
  ~148 detail pages per month: the backfill completes in **about three months**, fully automatic via
  the staged backfill and the credit budget.
- **If the spike shows `js_render` is unnecessary**, the whole backfill costs ~3,600 credits and
  finishes **within the first month**. This is why question 1 of the spike is worth answering before
  anything else.

**Expansion path.** Each additional Valencia neighbourhood roughly doubles this. Arrancapins is
estimated at ~250 sale and ~150 rent ⇒ 14 search pages, ~1,500 credits/month for observations plus a
~10,000-credit one-off backfill. On Free that means adding roughly one neighbourhood every two
months; **Build at €16/month (45,000 credits)** would cover several neighbourhoods at once. Launch
at €58/month (250,000 credits) only becomes necessary for all of Valencia city (~112,000
credits/month). The decision can be deferred until the first neighbourhood is actually added.

**Cost drivers & cheaper alternatives:** the ordered levers are (1) disable `js_render` if the spike
allows it (factor 2.5), (2) fetch each detail page only once — already in the design and by far the
largest structural saving, (3) sale only and add rent later, (4) search pages every two weeks
instead of weekly.

**Budget check:** yes — €0/month for the starting scope, with the backfill staged across
approximately three Free months. `--credit-budget` additionally caps every single run.

## Success criteria

- [ ] A run over a configured search area collects all listing URLs across all pages and produces a
      validated record for every reachable detail page.
- [ ] `--max-pages 10` and `--max-listings 10` provably bound the number of requests.
- [ ] `--credit-budget` stops the run in a controlled way and writes a partial report.
- [ ] `--cards-only` provably issues no detail page request.
- [ ] A replay run from stored raw HTML produces identical records without a network call.
- [ ] A mutated fixture with a renamed price class is parsed correctly via the fallback; a fixture
      without any price selector is quarantined and the run ends with an error.
- [ ] The full test suite is green via `unittest discover`; the superseded browser notebooks and
      their tests are removed.
- [ ] Every behavior was implemented test-first and the focused plus affected suites pass.
- [ ] No secrets, personal data or data files are included in the commit.

## Open questions & risks

- **Risk:** the Free allowance is 5,000 credits with **no rollover**, so unspent credits are lost and
  an overspend stops collection for the rest of the month. *Mitigation:* `--credit-budget` per run
  plus the staged backfill; the run stops cleanly and resumes next month rather than failing.
- **Risk:** ZenRows returns a challenge page with HTTP 200 when blocked. A naive parser would turn
  that into an empty record — and would silently burn credits. *Mitigation:* required-field contract
  plus an explicit challenge marker check; such pages are quarantined and counted as errors.
- **Risk:** a listing is edited after publication (renovation, new photos, changed size), so the
  fetch-once rule would keep a stale detail record. *Mitigation:* accepted deliberately — the
  observation table still tracks price, `listing_detail` carries `observed_at` and
  `extraction_version`, and a targeted re-fetch of selected ids remains possible later. Revisit if
  Silver shows card values drifting away from the stored detail record.
- **Risk:** the coverage threshold fires on genuinely incomplete real listings. *Mitigation:*
  calibrate the thresholds from the first real run instead of guessing.
- **Risk:** the 60-page cap silently truncates an area that grows past 1,800 listings.
  *Mitigation:* the crawler reports `page_cap_reached` per target, so it surfaces as a signal to
  split the area rather than as missing data.
- **Assumption:** ~360 listings in L'Eliana. Phase 0 reads the real result count from the search
  page and replaces the estimate in this plan, which in turn fixes the backfill schedule.
- **Assumption:** the confirmed selectors survive the ZenRows round trip. The stored raw HTML from
  the spike settles this before any parser is written.
- **Resolved reference:** the ScrapingBee article on scraping Idealista has now been read
  (see "External cross-check"). It confirms the card and pagination selectors and names Datadome as
  the anti-bot system, and changes nothing in this plan.
- **Risk:** Idealista is protected by **Datadome** (named explicitly in the ScrapingBee article),
  which is why a request needs `premium_proxy` and why a block can arrive as an HTTP 200 challenge
  page. *Mitigation:* already covered by the challenge marker check and the required-field contract;
  the spike additionally compares extracted id sets rather than HTML length.

## Progress log

- **2026-09-19 — Task 0.3 executed (live evidence).** Answers to the spike questions, all from
  captured payloads under `data/raw/idealista/search/` (gitignored):
  1. **`js_render` is required — Question 1 answered NO.** Without it ZenRows returns
     `422 RESP001 "Could not get content. try enabling javascript rendering for a higher success
     rate"`. With it the same URL returns 30 cards. The 25-credit assumption stands and the
     backfill keeps its ~2-month schedule; there is no cheaper mode.
  2. **`422 RESP001` is transient and billed at zero** (`X-Request-Cost: 0`). The identical request
     that failed succeeded on a later attempt. **This must be added to the retryable set in task
     2.1, which currently lists only 429/5xx.** Retrying a 422 is free, so the retry is pure upside.
  3. **`wait_for` materially improves reliability.** `js_render` + `premium_proxy` alone failed
     intermittently; adding `wait_for=article.item` (or `div.listing-top` for pages that may have no
     cards) succeeded on the first attempt every time. `mode=auto` also worked. Recommend
     `wait_for` as the default for search pages.
  4. **The block signature is HTTP 200 with a head-only document** — ~5.5 KB, a real `<title>`, and
     an empty `<body>`. Critically, `window.ddjskey` and `dd.idealista.com` appear on **good** pages
     too, so they are *not* challenge markers. This confirms M4: the only safe test is the positive
     one. Captured as `tests/fixtures/idealista_search_page_challenge.html`.
  5. **The canonical sort URL is `?ordenado-por=fecha-publicacion-desc`**, read from the page's own
     filter links — not the bare `?fecha-publicacion-desc` seen in the address bar. This matters:
     with the **canonical** form `li.next` **preserves** the sort
     (`/…/pagina-2.htm?ordenado-por=fecha-publicacion-desc`), while with the **bare** form it does
     **not** (`/…/pagina-2.htm`). Use the canonical form; the M8 caveat then resolves itself, and
     asserting the sort per page stays cheap insurance.
  6. **Volumes confirmed from the pages themselves:** sale **215**, rent **42** (30 on page 1 plus
     12 on page 2), matching the municipality index exactly.
  7. **Confirmed selectors.** Result count: `span#h1-container__text` ("42 casas y pisos en alquiler
     en L'Eliana, València"). Price row: `span.item-price` (current), `span.pricedown_price`
     (previous), `span.pricedown_icon` (drop %), and `span.item-price-by-area` (€/m², **sale pages
     only**, 29 of 30 cards). The parser must key on these classes and never on "the second price in
     the row", or a sale card's €/m² would be read as a previous price. Freshness badge (L5):
     `span.item-detail.txt-highlight-red`, e.g. "7 horas"; present on 2 of 4 fixture cards, so both
     branches are testable.
  8. **`data-element-id` equals the `a.item-link` href id** on every card in the committed
     fixtures — L1 verified in the fixture itself.

  9. **A zero-result search returns HTTP 404, not an empty page — task 0.3 is therefore complete
     with three fixtures, not four.** What first looked like a blocker was the answer. The repeated
     404s were not invalid URLs: a controlled pair on the *same* two filter slugs settles it. In the
     order the site itself generates, `con-chalets,metros-cuadrados-mas-de_900` (one match) answers
     **200** on every attempt; `con-chalets,de-un-dormitorio` (no match, the only >900 m² rental has
     5 bedrooms) answers **404** on every attempt. Order is irrelevant; the status carries the
     meaning. ZenRows relays it as `RESP002` with the explicit text "The requested URL page returned
     a 404 HTTP Status Code", so it is Idealista's 404, not the provider's.

     This **strengthens** M4. The distinction no longer depends on matching Spanish marker text that
     any copy edit could break:

     | Response | Meaning | Handling |
     | --- | --- | --- |
     | 200 + full page with `span#h1-container__text` | valid search page | parse; any card count |
     | 200 + head-only document, empty `<body>` | Datadome challenge | quarantine, count as error |
     | 404 / `RESP002` | the search genuinely has no results | distinct outcome, not an error |
     | 422 / `RESP001` | ZenRows could not fetch | retry; billed at zero |

     Consequences, applied: task 1.4 keys on this taxonomy and its empty-result fixture is dropped
     as unobtainable by construction; task 2.1's retry set gains 422/RESP001; for a configured
     target with `expected_listings > 0` a 404 is itself a drift signal, since such a target must
     never legitimately be empty.

  **Task 0.3 is complete.** Three fixtures committed, every spike question answered, no open
  dependency for Phase 1.

  **Credit use:** roughly 15 billed requests, far above the ~4 the task estimated. Failed requests
  cost nothing, but the hunt for a zero-result page and the fixture-coverage rework were not
  budgeted. ZenRows reported `X-Request-Cost: 0.025` per successful request; check the dashboard for
  the authoritative monthly figure before task 4.4.

- **2026-09-18** — Plan created. Verified up front: no JSON-LD or `utag_data` on the detail page, so
  a selector registry rather than structured extraction.
- **2026-09-18** — Open questions decided autonomously while the user was unavailable (see "Decided
  constraints"): two cadences, enforced credit budget, staged backfill, `js_render` stays on,
  browser notebooks removed.
- **2026-09-18** — User feedback applied: records renamed to `ListingObservation` and
  `ListingDetail` because they feed the two requested tables; the notebook requirement was removed
  from the workflow files while the `js_render` notebook stays as a deliberately chosen validation
  spike.
- **2026-09-18** — Second round of user feedback: starting scope narrowed to **L'Eliana only** and
  the plan re-costed for the **Free** ZenRows plan (no purchase before the pipeline is proven).
  Detail pages are now fetched **once per listing id and never again**, since the card already
  carries the price, the previous price and the drop percentage — this removes the price-change
  re-fetch entirely. The 60-page / 1,800-listing cap and the neighbourhood URL form are now
  confirmed facts rather than assumptions, as are the card and pagination selectors including
  `article.item[data-element-id]`.
- **2026-09-18** — The linked ScrapingBee article was read and cross-checked against the plan (see
  "External cross-check"). It confirms the card and pagination selectors, confirms the absence of
  structured data, and names Datadome as the anti-bot system. No plan change followed from it; the
  `js_render` question remains open for the spike.
- **2026-09-18** — Reviewed by `@reviewer` (see `dev/reviews/REVIEW-FEATURE-001.md`): **Approved**
  with seven corrections, all folded into `dev/plans/technical/FEATURE-001-technical-plan.yaml`
  (20 tasks). The corrections that change this plan's text on its next edit: the local output
  contract is JSONL in FEATURE-002's layout (M1), the credit budget gains a month-to-date ledger
  derived from the run reports because a per-run budget alone cannot protect a non-rolling monthly
  quota (M2), a search page counts as valid only with at least one card **or** an explicit
  no-results marker so a Datadome challenge can never be recorded as an empty area (M4), detail
  fetches per listing id are capped at 3 attempts (M5), and fetching is **sequential** rather than a
  thread pool at this scope (M6). Reviewer effort estimate: ~25.5h against the planned ~12h.
- **2026-09-19** — Review revised after the user supplied the site's navigation surfaces and their
  listing counts. Three corrections apply to this plan's text on its next edit. **Volume:** L'Eliana
  has **215** sale listings, not the estimated ~300, read from
  `/venta-viviendas/valencia-provincia/municipios`; the backfill therefore completes in ~2 Free
  months rather than ~3. **Granularity (M9):** Valencia expansion uses **district** URLs
  `/venta-viviendas/valencia/<district>/`, not neighbourhood URLs — the city holds 5,462 sale
  listings and its largest district 553, so ~19 targets cover it instead of ~70; area discovery
  stays a manual browser step using the municipality and zone indexes, which also give the count
  needed to check the 1,800 cap before adding a target. **Crawl order (M8):** a search page is
  processed as a complete unit — cards, then that page's new detail pages, then `li.next` — for
  checkpointing and bounded memory, not for bot evasion, which ZenRows makes irrelevant since every
  request gets a fresh residential IP and no shared session. The `data-element-id` assumption is now
  confirmed: the captured card carries `data-element-id="111804117"` around
  `a.item-link[href="/inmueble/111804117/"]`.
- **2026-09-19** — Both remaining open questions closed from the user's captures. **Rent volume:**
  L'Eliana has **42** rental listings (`/alquiler-viviendas/l-eliana-valencia/`), so the starting
  scope is 215 + 42 = **257 listings over 10 search pages**; the backfill is ~6,425 credits and
  completes in ~1.7 Free months. **Recency sort:** it is the bare query `?fecha-publicacion-desc`
  (not `?ordenado-por=…`), so every target is requested sorted and page order equals recency, which
  makes the staged backfill genuinely newest-first. One caveat carried into task 0.3: if the
  `li.next` href drops that query, page 2 would silently return relevance order, so the crawler
  re-applies the sort to every page URL. **New field (L5):** the card carries a relative freshness
  badge ("6 horas"); it is stored verbatim as `freshness_label` because it is the only signal that
  can date a listing published before collection began, and it is deliberately not interpreted in
  Bronze.
