# Review — FEATURE-001: Region-wide Idealista collection with drift-resistant extraction

**Reviewer:** `@reviewer` · **Date:** 2026-09-18 · **Revised:** 2026-09-19 ·
**Plan:** [FEATURE-001](../plans/FEATURE-001-region-listing-crawl.md)
**Verdict:** ✅ Approved — with nine documented corrections folded into the technical plan

## Summary

The outcome is feasible and the two decisions that carry the feature — one detail fetch per listing
id, and a card-derived observation series — are sound and correctly justified. The plan's factual
claims about the repository all hold under verification. What it does not yet specify is how a
record reaches disk, how the monthly credit quota is enforced across runs, and how a Datadome
challenge is distinguished from a genuinely empty search area; each is a local technical omission
that repository evidence resolves unambiguously, so the technical plan supplies them rather than
returning the plan to the Architect. The effort estimate is the one number that does not survive
review: roughly twice the stated 12 hours.

## What changed in the 2026-09-19 revision

The user supplied the site's own navigation surfaces and their listing counts. Three things follow,
and all three make the feature cheaper or simpler:

1. **Area discovery is a solved problem and needs no code.** Idealista publishes an index of
   municipalities per province and a zone index per city, each with an authoritative listing count.
   Picking a target and checking it against the 1,800-listing cap is a browser task done once per
   expansion, not a runtime dependency (**M9**).
2. **District granularity is enough for Valencia city** — the largest district holds 553 listings,
   far below the cap. The plan's neighbourhood-level targets are one level too deep: ~19 targets
   instead of ~70 for identical coverage (**M9**).
3. **L'Eliana has 215 sale listings, not the estimated ~300.** The backfill shrinks accordingly and
   now completes in roughly two Free months rather than three (see "Effort and cost recheck").

The user also proposed interleaving detail fetches with each search page so the traffic looks less
like a bot. The ordering is adopted, but for different reasons than proposed — the anti-bot
rationale does not survive contact with how ZenRows works (**M8**).

A second batch of screenshots closed both questions this revision had left open: the rent volume is
**42** listings, and the "Recientes" sort is the URL query `?fecha-publicacion-desc`, which makes
M8's page-order priority genuinely newest-first. The same captures revealed a freshness badge on the
card that is worth storing (**L5**).

One open assumption is now closed: `data-element-id` and the `/inmueble/<id>/` href carry the same
id on the same card (**L1**).

## Evidence checked

- **Plan and dependencies:** `dev/plans/FEATURE-001-region-listing-crawl.md` (🔵 Planned),
  `dev/plans/FEATURE-002-s3-bronze-storage.md` (object layout and sink protocol — the source that
  disambiguates FEATURE-001's local output), `dev/plans/FEATURE-003-scheduled-container-run.md`,
  `dev/plans/README.md` (rows for 001–003 present, all 🔵).
- **Code, tests, data, and configuration:**
  - `src/idealista/zenrows_source.py` — verified: `js_render`, `premium_proxy`, `proxy_country`
    parameters and an injectable `HttpGet` already exist; there is no credit accounting, no retry,
    no concurrency. The plan's "current state" is accurate.
  - `src/idealista/listing_parser.py` — verified: fixed single selectors (`.info-data-price`,
    `.pricedown_price`, `.pricedown_icon`, `.main-info__title-main`, …), missing fields silently
    become `None`, and `price_per_sqm` is computed as a `float`. The plan's problem statement is
    accurate.
  - `python -m unittest discover -s tests -t .` → `ImportError: Start directory is not importable`.
    The plan's claim that discovery is broken is **confirmed**; `tests/__init__.py` is absent.
  - Per-module runs: `test_idealista_listing_parser` 8 OK, `test_zenrows_source` 6 OK,
    `test_validate_workflow` 3 OK, `test_idealista_playwright_notebook_entrypoint` **FAILED**
    (1 failure, 3 errors), `test_idealista_playwright_stealth_notebook` **FAILED**
    (`KeyError: 'language'`, 0 tests run). The plan's claim that the notebook tests have been
    failing is **confirmed**.
  - `.gitignore:100` — `/data/*` is ignored, so raw HTML and records stay out of git. Confirmed via
    `git check-ignore -v data/raw/idealista/106749418_20260918T150354Z.html`.
  - `tests/fixtures/idealista_listing.html` — 2,174 bytes, hand-reduced, no contact data
    (`grep -ciE "telefono|tel:|@|agencia|profesional"` → 0). This is the fixture style to preserve.
  - `README.md:76` — "The project does not bypass authentication, CAPTCHAs, access controls, or
    anti-bot protections." This **contradicts** `.github/copilot-instructions.md` (which permits
    managed scraping APIs and residential proxies since commit `a4ce725`) **and the code already
    merged** in `4cd81ea`, which sends `premium_proxy=true`.
  - `dev/tools/validate_workflow.py` — `ALLOWED_CHECKS` is
    `{python-lint-and-test, node-test, terraform-validate, workflow-consistency}`; it also verifies
    that `reviewed_plan` exists on disk and that `total_tasks` matches the task count.
  - `.github/workflows/` **does not exist**, although `.github/agents/WORKFLOW.md` links
    `workflows/workflow-consistency.yml`. No lint, type, or coverage configuration exists
    (`pyproject.toml`, `setup.cfg`, `ruff.toml`, `mypy.ini`, `pytest.ini` all absent).
  - `yaml` is not importable in `.venv`; the plan's addition of PyYAML to `requirements.txt` is a
    genuine prerequisite, not a formality.
- **Evidence reviewed:**
  - **Reproduced in an isolated copy** (scratchpad, repository untouched): adding `tests/__init__.py`
    makes discovery work (21 tests, 5 failures — all from the two notebook test modules);
    additionally deleting those two modules yields **17 tests, OK**. This confirms that the plan's
    Phase 4 cleanup produces a green suite, and it fixes the exact command the technical plan uses.
  - **The ScrapingBee article was read** and is recorded in the plan under "External cross-check".
    It independently confirms `article.item` and `li.next > a`, confirms the absence of structured
    data, and names **Datadome** as the anti-bot system. It does **not** settle the `js_render`
    question (its Selenium route renders JavaScript by definition) and does not know the 60-page cap.
  - **Technical plan verified structurally:** 20 tasks, dependency graph acyclic, every
    `depends_on` and `can_run_parallel_with` resolves to an existing task, the declared critical
    path is a real dependency chain (13.5h serial), every `files_to_create`/`files_to_modify`
    path is contained in `allowed_files`, no allowed/forbidden overlap, all statuses
    `not_started`, every behavior task carries a complete `tdd` block. `validate_workflow.py`
    passes.
  - **Not reproduced:** the Phase 0 spike has not been run — it costs live credits and is itself the
    first task of the technical plan.
- **Unverified assumptions:**
  - *`js_render` can be disabled for search pages* — owner: Implementer, verification point: task 0.3.
    Nothing downstream breaks if it is false; only the backfill schedule changes.
  - *The confirmed selectors survive the ZenRows round trip* — verification point: task 0.3.
  - *`li.next` preserves the sort query* — see "Sort order and rent volume"; verification point:
    task 0.3, with an explicit fallback if it does not.

## Navigation and volume evidence (user screenshots, 2026-09-19)

The user walked the site's own navigation and captured both the DOM and the listing counts. This
closes the plan's "how do we get from an area to listing URLs" question and supplies authoritative
volumes. All of the following is observed, not inferred:

**Area discovery surfaces**

| Surface | URL | What it yields |
| --- | --- | --- |
| Municipality index per province | `/venta-viviendas/valencia-provincia/municipios` | every municipality with its listing count; L'Eliana → `/venta-viviendas/l-eliana-valencia/`, **215** |
| Zone index per city | `/venta-viviendas/valencia-valencia/mapa` | every district with its count, linking to `/venta-viviendas/valencia/<district>/mapa` |
| Zone index per district | `/venta-viviendas/valencia/extramurs/mapa` | every neighbourhood with its count, linking to `/venta-viviendas/valencia/<district>/<neighbourhood>/mapa` |

Counts read from these pages: València provincia **23,442** · Valencia city **5,462** · districts
Poblats Marítims 553, Quatre Carreres 544, Ciutat Vella 507, L'Eixample 392, Extramurs 378, Camins
al Grau 374, L'Olivereta 360, Jesús 345, Rascanya 313, Patraix 312 · within Extramurs: Arrancapins
147, La Petxina 105, La Roqueta 64, El Botànic 62.

**Card DOM, confirmed on the live L'Eliana result page**

- `section.items-container.items-list` wraps the results.
- A card is `article.item` with `data-element-id="111804117"` plus `data-online-booking`,
  `data-is-invoice-ad`, `data-is-professional-ad` and `data-is-offmarket`.
- Inside: `div.item-info-container` → `a.item-link[href="/inmueble/111804117/"]` (carries
  `role="heading"` and a `title`), `div.price-row`, `div.item-detail-char`,
  `div.item-description.description`, `div.listing-tags-container`, `div.item-toolbar`.
- `span.highlighted-text` ("Top", "Destacado") sits **outside** and before the `article`, so a card
  selector must not treat it as part of the card.
- `div.item-detail-char` example: `Garaje incluido 4 hab. 223 m²` — the first token is not always
  numeric, so parsing must match on unit keywords rather than on position.
- The price row carries `598.000 € 620.000 € ↓4%`, confirming current price, previous price and
  drop percentage on the card.
- The page footer carries `Precio medio 2.788 eur/m²` and an `Ordenar: Relevancia | Baratos |
  Recientes | Más` control.

**Pagination, confirmed**

- `div.pagination > ul`, with `li.moreresults`, `li.selected` and
  `li.next > a[rel="nofollow"].icon-arrow-right-after[href]`.
- The href is relative and of the form `/venta-viviendas/l-eliana-valencia/pagina-2.htm`.
- The numeric page list is a **sliding window** (observed as `1…6`, `47…51`, `55…60`), so the last
  page number cannot be read off page 1. Following `li.next` until it disappears is the only correct
  strategy — which is what task 3.1 already does.
- The 60-page cap is confirmed again on a Valencia city search, where pagination ends at 60 and the
  page states "¿Has visto 1.800 viviendas…".

**Consequence for the plan's problem statement.** Problem 1 ("there is no path from a search area to
listing URLs") remains an accurate description of the *code*, but the *site* makes discovery
trivial: collecting the cards of a search already yields every listing URL for that area, and the
index pages above supply the areas themselves. No link-discovery crawler is needed — see M9.

## Sort order and rent volume (user screenshots, 2026-09-19, second batch)

Both questions left open by the first revision are now closed, and a third finding fell out of the
same captures.

**Rent volume.** `/alquiler-viviendas/l-eliana-valencia/` states "42 casas y pisos en alquiler en
L'Eliana, València", with the breadcrumb València provincia 5,687 → El Camp de Túria 229 →
L'Eliana 42. So the operation prefix is `alquiler-viviendas` against `venta-viviendas`, and the
starting scope is **215 sale + 42 rent = 257 listings** over 8 + 2 = **10 search pages**.

**The "Recientes" sort is a URL.** `/alquiler-viviendas/l-eliana-valencia/?fecha-publicacion-desc`,
rendered from `div#order-by[data-param="ordenado-por"]` → `ul.view-type-toolbar-buttons` → an anchor
with `data-value="fecha-publicacion-desc"` and `class="btn regular smaller selected"`. Note the
query is a **bare key with no value**, not `?ordenado-por=fecha-publicacion-desc`. M8's
reconciliation therefore holds: request every target sorted by recency so page order equals
recency, and task 3.4's page-order priority is genuinely "newest first".

**One caveat this creates.** If the `li.next` href is a bare path such as `pagina-2.htm`, following
it would silently drop the sort and page 2 would come back in relevance order — a defect that
produces plausible-looking data. Task 0.3 must check the next-page href on a sorted page; if the
query is absent, the crawler re-applies the sort to every page URL it builds. The selected-sort
anchor carries `class="… selected"`, which is a cheap positive assertion that the sort actually took
effect on each page.

### 🟢 L5 — The card carries a freshness badge worth capturing

- **Evidence:** on both the relevance-sorted and the recency-sorted rent results, cards show an
  orange relative-time badge next to the floor description — "6 horas", "21 horas" — on the same
  card the parser already reads.
- **Why it matters:** the feature derives time-on-market purely from our own observation history,
  which means every listing that existed before collection started has an unknown start date. A
  publication-age badge closes that cold start for anything recent, at zero extra requests.
- **Caveat:** the badge's exact semantics are not established — it may mean published or last
  updated, and it appears to be shown only for recent listings. Do not interpret it in Bronze.
- **Suggestion:** add one nullable raw string field to `ListingObservation` (for example
  `freshness_label`) and store the badge text verbatim. Parsing and interpretation belong to Silver,
  where the ambiguity can be resolved against our own `first_seen` series once both exist.
- **Benefit:** one selector and one field now, versus an unrecoverable gap in the earliest weeks of
  history. Folded into tasks 1.1 and 1.3.

## Gate result

| Gate | Result | Evidence / required action |
| --- | --- | --- |
| Outcome and scope are measurable and bounded | Pass | Success criteria are observable; the starting scope is two search targets and expansion is a config line (Decided constraint 7) |
| Repository and dependency assumptions match reality | Pass | Every "current state" claim reproduced above, including the two failing test modules and broken discovery |
| Supporting evidence is reproducible and sufficient | Pass | Harness repair reproduced in an isolated copy; the one open evidence item (the spike) is the first task and cannot change the design, only the schedule |
| Design is the simplest adequate option | Pass | After M6 (no thread pool) and M9 (district targets, discovery stays manual) |
| TDD slices and validation commands are executable | Pass | Commands verified against the repository; only `workflow-consistency` is required as a CI gate (L3) |
| Data integrity, scraping, privacy, and security are addressed | Pass | After M1 (output contract), M4 (challenge detection) and M7 (README policy); `/data/*` is gitignored and the existing fixture style carries no contact data |
| Operations, recovery, migration, and cost are addressed | Pass | After M2 (monthly ledger), M5 (attempt ledger) and M8 (per-page checkpointing); the cost model was recomputed against the real 215-listing count |

## Strengths

- **One detail fetch per listing id (Decided constraint 2) is the correct central decision.** The
  card already carries price, previous price and drop percentage, so re-fetching a detail page buys
  nothing. Verified against the plan's own cost model: it is what turns steady-state detail traffic
  from a full pass into ~25 requests per month. Preserve it through implementation.
- **Rebuilding the known-id set from the stored records rather than a side state file.** A lost
  state file then cannot cause silent gaps or duplicate spending. This is worth the small read cost.
- **Separating raw observations from derived values.** `first_seen`, `days_on_market` and
  `price_per_sqm` all stay out of Bronze. This matches the repository's facts-vs-inference rule and
  keeps FEATURE-002 honest.
- **Following `li.next` rather than reading the last page number.** The new evidence shows the
  numeric page list is a sliding window, so this choice — already in task 3.1 — is not merely
  simpler but the only correct one.
- **The cost model's method is sound; only its input was stale.** Recomputed against the
  authoritative count in "Effort and cost recheck" below.

## Effort and cost recheck (2026-09-19)

Both volumes are now authoritative: **215** sale listings from the municipality index and **42**
rent listings from the rent search page. At 30 cards per page that is 8 + 2 = 10 pages per pass.

| Item | Requests | @ 25 credits |
| --- | --- | --- |
| Search pages, weekly (4.33 × 10) | ~43 / month | ~1,083 |
| Detail pages, new ids only | ~25 / month | ~625 |
| **Steady state** | **~68 / month** | **~1,708** (34 % of the Free allowance) |
| Initial backfill (257 details, one-off) | 257 | ~6,425 |

Backfill pacing: (5,000 − 1,083) / 25 ≈ **156 details per month**, so 257 details complete in **~1.7
months** rather than the ~2.4 previously calculated. If the spike shows `js_render` is unnecessary,
the whole backfill fits inside the first month with room to spare.

For the later Valencia expansion the real figure is now known: **5,462** sale listings across ~19
district targets, roughly **183 search pages** per pass. That is ~137,000 credits of one-off
backfill and ~20,000 credits per month of observations — the point at which the Launch plan, not
Build, becomes the relevant option. Worth knowing before committing to city-wide coverage.

- **The 60-page cap is handled as a signal (`page_cap_reached`), not as silent truncation.** This is
  the difference between an area that outgrows a search and missing data nobody notices.

## Findings

### 🟡 M1 — No output contract: idempotency cannot be implemented or tested as specified

- **Problem:** the plan asserts "Idempotency: a second run on the same day produces the same records
  (key = `listing_id` + `observed_date`), never duplicates" and lists it as a success criterion, but
  names no output format, no output path and no writer module. `Files → Create` contains parsers,
  the crawler, models, the cached fetcher and the CLI — nothing that persists a record.
- **Evidence:** `dev/plans/FEATURE-001-region-listing-crawl.md`, sections "Contracts and
  invariants", "Files", and success criterion 1. Meanwhile
  `dev/plans/FEATURE-002-s3-bronze-storage.md` already fixes the table names
  (`listing_observations`, `listing_details`, `quarantine`, `runs`) and the `observed_date`
  partitioning for the S3 layout.
- **Impact:** the Implementer would invent an on-disk layout that FEATURE-002 then has to either
  mirror or migrate, and the idempotency criterion would have nothing to assert against.
- **Recommendation:** write newline-delimited JSON locally under the **same table names and the same
  `observed_date` partitioning FEATURE-002 defines**, so the later sink is a substitution rather
  than a migration:
  `data/bronze/idealista/<table>/operation=<sale|rent>/observed_date=YYYY-MM-DD/<target>.jsonl`.
  The dedup key is `(listing_id, observed_date)` for observations and `listing_id` alone for
  details; a re-run rewrites the day's file from the merged set instead of appending.
- **Owner / verification:** Reviewer — **resolved in this review**. Implemented as technical-plan
  task 4.1 with an explicit re-run test. FEATURE-002 replaces the writer with `BronzeSink`; the
  record contracts are unaffected.

### 🟡 M2 — A per-run credit budget does not protect the monthly quota

- **Problem:** Decided constraint 3 claims the enforced budget "is what keeps a mistake from
  consuming a whole month". It does not. `--credit-budget` bounds a single run; four weekly runs
  plus a backfill pass, each individually within budget, can still exhaust the 5,000 credits. There
  is no month-to-date accounting anywhere in the plan, and the allowance does not roll over.
- **Evidence:** "Decided constraints" 3 and 4 vs. "Constraints" (5,000/month, no rollover). No
  component in `Files → Create` holds cross-run state; the staged backfill's "remainder carries over
  to the next run" likewise has no defined home.
- **Impact:** the plan's binding constraint is unenforced. An overspend stops collection for the
  remainder of the month — precisely the failure the user asked to avoid before committing to a paid
  plan.
- **Recommendation:** derive the month-to-date spend from the run reports already being written
  (`data/bronze/idealista/runs/observed_date=*/*.json`, filtered to the current UTC month) and stop
  the run when `monthly_budget − month_to_date` is exhausted, with
  `stopped_reason = "monthly_budget_exhausted"`. No new state file, no new failure mode: the reports
  are the ledger. The per-run budget stays as the second, tighter bound.
- **Owner / verification:** Reviewer — **resolved in this review**. Technical-plan task 2.3, with a
  test that seeds two prior reports and asserts the third run stops early.

### 🟡 M3 — The Phase 0 spike is both a single point of failure and the only fixture source

- **Problem:** every Phase 1 RED test needs a search-page fixture, and the plan sources all of them
  from the live spike. If ZenRows returns a Datadome challenge on the first attempt, no parser work
  can start and the credits are spent for nothing.
- **Evidence:** "Validation spike (notebook)" — "store the raw HTML, then analyse strictly offline.
  The stored pages become redacted test fixtures." Phase 1's first task depends on that fixture. The
  ScrapingBee article reports a captcha on a first run as the normal case, not the exception.
- **Impact:** an avoidable dependency between a paid, blockable network call and all deterministic
  parser development.
- **Recommendation:** decouple them. The fixture may equally come from the browser the user already
  used to confirm the selectors (save the search page, or copy `document.documentElement.outerHTML`
  from DevTools) at **zero credits** — and that HTML is *more* trustworthy for selector work, since
  it is what the site actually serves. The spike then answers only what a browser cannot: whether
  ZenRows **without** `js_render` returns the same 30 ids. Parser tasks depend on the fixture, not
  on the spike.
- **Owner / verification:** Reviewer — **resolved in this review**. Task 0.3 accepts either source
  and names the browser route as the fallback; tasks 1.3 and 1.4 depend on the fixture only.

### 🟡 M4 — A challenge page and an empty search area are indistinguishable as specified

- **Problem:** the plan names "an explicit challenge marker check" but never defines the marker, and
  it separately requires that a page with no results returns an empty list "without raising". Both a
  Datadome challenge and a genuinely empty area produce HTTP 200 with zero cards. As written, a
  blocked run would be recorded as "this area has no listings" — silent data loss that also looks
  like a successful run.
- **Evidence:** "Risks" (ZenRows returns a challenge page with HTTP 200) vs. Phase 1 task 2 ("a page
  without results returns … an empty observation list without raising").
- **Impact:** the worst failure mode in the feature: wrong data that reports itself as healthy, in
  the one dimension (a listing's disappearance) the whole time-on-market analysis rests on.
- **Recommendation:** make the distinction positive rather than negative. A page counts as a valid
  search page only if it carries **either** at least one `article.item[data-element-id]` **or** an
  explicit no-results marker from the result-count element. Anything else is quarantined and counted
  as an error, never as an empty area. Derive the concrete marker text from the stored HTML in task
  0.3 and put it in the selector registry, where a change is a data edit.
- **Owner / verification:** Reviewer — **resolved in this review**. Technical-plan task 1.4, with
  three fixtures: a last page, an empty result page, and a challenge page.

### 🟡 M5 — A permanently unparseable detail page is re-fetched on every run, forever

- **Problem:** the known-id set is rebuilt from stored `listing_detail` records. A quarantined detail
  page writes no record, so its id stays unknown and is re-selected on every subsequent run. Useful
  self-healing for a transient block; an unbounded credit leak for a page that never parses.
- **Evidence:** "Two consequences worth naming" (the known-id set is rebuilt from stored records)
  combined with the required-field contract that quarantines instead of writing.
- **Impact:** at 25 credits per attempt, a handful of permanently broken listings quietly consumes a
  measurable share of a 5,000-credit month, and does so more each time the corpus grows.
- **Recommendation:** record failed detail attempts with an attempt counter alongside the quarantine
  entry and exclude an id from selection after 3 failures, surfacing the count in the run report so
  a systematic breakage (a selector change affecting every page) is still visible as a spike rather
  than hidden by the cap.
- **Owner / verification:** Reviewer — **resolved in this review**. Technical-plan task 3.3.

### 🟡 M6 — Bounded concurrency is unjustified complexity at the starting scope

- **Problem:** the plan specifies a thread pool with bounded concurrency (default 5) in
  `zenrows_source.py`. The starting scope is ~12 search pages per weekly pass and at most ~148
  detail pages per month.
- **Evidence:** "Design → OOP / SOLID" and "Operational and compliance impact" (bounded concurrency,
  default 5) vs. "Estimated monthly cloud cost" (~52 search requests/month). `copilot-instructions.md`
  requires the smallest coherent change and forbids speculative capability; the same section also
  requires "human-like pacing", which a five-way parallel fetch works against.
- **Impact:** concurrency plus retries plus a credit budget plus a monthly ledger interact; every
  additional axis costs test complexity and failure modes for a workload that is a few dozen
  sequential requests.
- **Recommendation:** implement sequential fetching with a configurable pause. Keep the `HtmlFetcher`
  protocol — that boundary earns itself through `CachedHtmlFetcher` and FEATURE-003 — but drop the
  thread pool until an area actually makes a run too slow. It is a contained, additive change later.
- **Owner / verification:** Reviewer — **resolved in this review**. Task 2.1 specifies sequential
  fetching; FEATURE-001's plan text should be corrected on its next edit.

### 🟡 M7 — The README forbids what the merged code already does

- **Problem:** `README.md:76` states the project "does not bypass authentication, CAPTCHAs, access
  controls, or anti-bot protections", while `.github/copilot-instructions.md` explicitly permits
  managed scraping APIs and residential proxies, and `src/idealista/zenrows_source.py` (merged in
  `4cd81ea`) sends `premium_proxy=true` against a Datadome-protected site.
- **Evidence:** `README.md:73-79`, `.github/copilot-instructions.md` → "Scraping Rules",
  `git show 4cd81ea`.
- **Impact:** the repository's most public policy statement contradicts its own code. The plan
  schedules this fix as the last item of Phase 4, which leaves the contradiction standing through
  the entire implementation.
- **Recommendation:** move it to the first task. State the approved mechanism positively: public
  pages only, a managed provider with residential proxies, no authentication bypass, no account-only
  or paid-API data, bounded rate, stop on operator objection.
- **Owner / verification:** Reviewer — **resolved in this review**. Technical-plan task 0.1, ahead of
  all code tasks.

### 🟡 M8 — Adopt per-page crawl order, but not for the reason proposed

- **Problem:** the user proposes running the crawl as a human would browse — home page, province,
  municipality, page 1, all cards of page 1, all detail pages of page 1, then page 2 — on the
  grounds that it is "safer" against bot detection. The technical plan currently collects every
  observation across all pages first (task 3.1) and only then selects detail fetches (task 3.2).
- **Evidence:** the anti-bot premise does not hold for this architecture.
  `src/idealista/zenrows_source.py` issues each request as an independent call to
  `https://api.zenrows.com/v1/` with `premium_proxy=true`. ZenRows routes every such call through a
  **different residential exit IP** and a fresh browser unless `session_id` is passed, which this
  code does not do. There is no cookie jar, no referer chain and no TLS session shared between two
  requests, so Datadome cannot observe the ordering at all. The three navigation hops (home →
  province → municipality) would cost 75 credits per run and transmit nothing the next request can
  use.
- **Impact:** if adopted for the stated reason, the feature would pay for navigation requests that
  buy nothing and would gain a false sense of protection. If rejected outright, a genuinely better
  execution structure would be lost with it.
- **Recommendation:** adopt the ordering, drop the rationale, and skip the navigation hops.
  - Process **one search page as a complete unit**: fetch the page, parse its cards, write its
    observations, fetch the detail pages for its unknown ids, write those, then follow `li.next`.
  - The reasons that do hold: a page boundary is a natural checkpoint, so a budget stop or a crash
    leaves a consistent prefix rather than a half-written run; memory stays bounded regardless of
    area size; and the run report can record progress per page.
  - Target URLs stay hardcoded in `config/search_targets.yaml`; discovery happens in a browser
    (M9), not at runtime.
  - **The one real conflict:** task 3.4 prioritizes the backfill "newest first" across the whole
    backlog, which requires all observations before any detail fetch. Per-page processing makes the
    priority *page order*. Reconcile the two by requesting the target with the site's "Recientes"
    sort so that page order **is** recency; confirm the sort parameter in task 0.3 and fall back to
    plain page order if it cannot be expressed as a URL.
  - **If blocks do appear**, the effective lever is ZenRows' `session_id` (one IP for up to ten
    minutes) or `custom_headers` for a referer — a one-parameter change, not a restructuring. Note
    it as the escalation path; do not build it now.
- **Owner / verification:** Reviewer — **resolved in this review**. Task 3.1 gains a per-page
  callback seam, task 3.2 is driven per page, task 3.4's ordering is page order, and task 0.3 adds
  the sort-URL question.

### 🟡 M9 — Target granularity is one level too deep, and discovery needs no code

- **Problem:** the plan and task 4.2 model Valencia expansion at **neighbourhood** level
  (`/venta-viviendas/valencia/<district>/<neighbourhood>/`, e.g. Arrancapins). The new evidence shows
  that is unnecessary, and separately that the plan has no answer for how an area is chosen at all.
- **Evidence:** Valencia city holds 5,462 sale listings; its largest district, Poblats Marítims,
  holds 553 — less than a third of the 1,800 cap. Arrancapins (147) is a neighbourhood inside
  Extramurs (378), and Extramurs alone fits comfortably in one search. Meanwhile
  `/venta-viviendas/valencia-valencia/mapa` and `/venta-viviendas/valencia/<district>/mapa` list
  every area together with its count.
- **Impact:** neighbourhood targets mean roughly 70 configuration entries and 70 paginated searches
  where ~19 would do — more requests, more configuration to maintain, and more chances for an area
  to be silently missed. The absence of a documented discovery step also leaves the 1,800 cap as
  something discovered only after a run truncates.
- **Recommendation:**
  - Use **district** URLs, `/venta-viviendas/valencia/<district>/`. Keep the neighbourhood form
    documented in the configuration as the fallback for the day a district passes 1,800.
  - Treat area discovery as a **documented manual step**, not code: read the municipality or zone
    index in a browser, check the count against the cap, add the URL to `config/search_targets.yaml`.
    This costs zero ZenRows credits and no implementation, and it is exactly the repository's
    "smallest coherent change" rule applied to a problem the site already solves.
  - Record the count in the configuration entry as `expected_listings`, so a run that returns wildly
    fewer observations than expected is visible as drift rather than passing silently.
- **Owner / verification:** Reviewer — **resolved in this review**. Task 4.2 ships district-form
  examples and the `expected_listings` field; the discovery procedure is documented in the README
  section that task 0.1 already touches.

### 🟢 L1 — The `data-element-id` assumption is now confirmed; keep the cross-check anyway

- **Evidence:** resolved on 2026-09-19. The captured L'Eliana card shows
  `article.item[data-element-id="111804117"]` containing
  `a.item-link[href="/inmueble/111804117/"]` — the attribute and the href carry the same id. The
  ScrapingBee article parses the id out of the href and does not mention the attribute, so the two
  are independent sources that agree.
- **Suggestion:** keep the planned equality assertion in task 1.3 regardless. It costs one line and
  turns a future divergence into a named drift signal rather than a silent id change.
- **Benefit:** the assumption is no longer load-bearing, and the assertion keeps it that way.

### 🟢 L2 — Keep committed fixtures reduced, not whole pages

- **Evidence:** `tests/fixtures/idealista_listing.html` is 2,174 bytes and hand-reduced; a real
  detail page is ~206 KB per the plan's own measurement, and a search page carries 30 agency names.
- **Suggestion:** commit the `section.items-container` subtree with three or four cards and the
  pagination block, with agency and contact markup stripped — not the full page.
- **Benefit:** keeps the privacy rule mechanical rather than a judgement call, and keeps diffs
  readable when a selector changes. Folded into task 0.3.

### 🟢 L3 — The CI gates named by the workflow do not exist

- **Evidence:** `.github/workflows/` is absent, yet `WORKFLOW.md` links
  `workflows/workflow-consistency.yml` and `validate_workflow.py` allows `python-lint-and-test`.
  There is no lint, type or coverage configuration in the repository.
- **Suggestion:** this technical plan requires only `workflow-consistency` and sets
  `min_coverage: null`. Adding the actual workflow files is separate repository work, not part of
  FEATURE-001.
- **Benefit:** avoids an approved plan depending on an invented CI gate.

### 🟢 L4 — The plan header claimed artifacts that did not exist

- **Evidence:** `FEATURE-001-region-listing-crawl.md:6-7` referenced `REVIEW-FEATURE-001.md` and
  `FEATURE-001-technical-plan.yaml` while neither existed; `validate_workflow.py` does not check the
  feature file's header, only `reviewed_plan` inside a technical plan.
- **Suggestion:** none needed — both artifacts exist as of this review.
- **Benefit:** noted so the template's boilerplate is not mistaken for a completed gate.

## Alternatives considered

- **Skip the observation series; re-scrape detail pages on a schedule.** Simpler to build, and
  removes the card parser entirely. Trade-off: costs roughly 15× the credits, and still misses every
  listing that appears and disappears between two passes. Verdict: stick with the plan — the card
  already carries the moving value, which is the whole reason this design is affordable on a free tier.
- **Persist directly to S3 and skip local output (merge FEATURE-002 into 001).** Removes the
  throwaway JSONL writer. Trade-off: couples the first proof of the pipeline to AWS credentials and
  Terraform, and contradicts the user's stated wish to prove the thing works before spending. Verdict:
  keep them separate; M1 makes the local layout a prefix of the S3 layout, so the later swap is a
  substitution and not a migration.
- **Parse the id from the href instead of `data-element-id`.** What the ScrapingBee article does.
  Trade-off: the href pattern is a URL contract and arguably as stable, but it is also what changes
  when the site reorganizes its routes. Verdict: keep `data-element-id` as primary, with the href as
  the registry's fallback and as the cross-check from L1 — this gets both.
- **Replay the user's navigation path at runtime (home → province → municipality → results).**
  The user's proposal, and intuitive. Trade-off: costs 75 credits per run and transmits nothing
  between requests, because ZenRows gives each call a fresh residential IP and a fresh browser.
  Verdict: rejected as a request sequence, adopted as an *execution* structure — see M8. The URLs it
  would discover are stable and belong in configuration.
- **Crawl Valencia at neighbourhood level.** What the plan currently specifies. Trade-off: ~70
  targets instead of ~19 for identical coverage, because every district already fits under the
  1,800-listing cap. Verdict: use districts; keep the neighbourhood form as the documented fallback
  (M9).

## Risks

| Risk | Likelihood | Impact | Mitigation | Owner / signal |
| --- | --- | --- | --- | --- |
| Datadome blocks ZenRows on search pages even with `premium_proxy` | Med | High | Task 0.3 runs 4 bounded requests before any code is written; the browser fixture route keeps parser work unblocked either way; `session_id` is the documented escalation (M8) | Implementer / task 0.3 returns a challenge page instead of 30 ids |
| `js_render` turns out to be required | Med | Low | Already budgeted: the backfill stretches to ~2 Free months via the staged backfill; no design change | Implementer / id sets differ in task 0.3 |
| A selector change silently halves field coverage | Low | High | Coverage thresholds fail the run with a non-zero exit; mutated fixtures test the fallback path | Implementer / `report.failed` with named fields |
| The monthly quota is exhausted mid-month | Low | Med | M2's month-to-date ledger stops the run cleanly with `stopped_reason`; M8's per-page checkpoint means the stop leaves a consistent prefix | Implementer / `stopped_reason = "monthly_budget_exhausted"` |
| `li.next` drops the `?fecha-publicacion-desc` query, so page 2 silently returns relevance order | Med | Med | Task 0.3 inspects the next-page href on a sorted page; the crawler re-applies the sort to every page URL and asserts the selected-sort anchor per page | Implementer / task 0.3 |
| The detail-once rule keeps a stale record after a listing is edited | Med | Low | Accepted deliberately; `observed_at` and `extraction_version` are recorded and a targeted re-fetch stays possible | User / Silver shows card values drifting from stored details |
| An area grows past the 1,800-listing cap and truncates silently | Low | Med | `page_cap_reached` per target, plus `expected_listings` from the zone index as a second signal (M9) | Implementer / run report |
| Effort overruns the plan's estimate | High | Low | Recorded below; the phase boundaries make a partial delivery useful on its own | User / Phase 1 completion time |

## Effort check

- **Plan estimate:** L (~12h)
- **Reviewer estimate:** L (~26h) — confidence Med
- **Why it differs / hidden complexity:** the plan counts the parsers and the crawler but not the
  surrounding work the same sections require: 20 atomic TDD slices across value objects, a selector
  registry, two parsers, a coverage report, a fetcher with retries and credit accounting, a monthly
  ledger, a replay fetcher, four orchestration behaviors, a writer, config loading and a CLI — plus
  the harness repair and the removals. The corrections that add scope (M1 writer, M2 ledger, M5
  attempt ledger) add ~3.5h between them and M8's per-page restructuring adds ~0.5h; M6 gives back
  ~2h and M9 costs nothing because it removes work rather than adding it. The estimate is not a
  reason to reduce scope: the phases are independently useful, and Phase 0 plus Phase 1 alone
  already answer the user's question of whether this works.

## Reuse & conflicts

- **Reuse:** `src/idealista/zenrows_source.py` — the injectable `HttpGet` seam and
  `build_zenrows_params` are directly reusable; the `HtmlFetcher` protocol wraps them rather than
  replacing them.
- **Reuse:** `src/idealista/listing_parser.py` — `parse_features`, the unit parsing helpers and the
  coordinate extraction carry over unchanged; only field resolution moves to the registry, and the 8
  existing tests must stay green through that refactor.
- **Reuse:** `src/scrape_listing_zenrows.py::save_raw_html` — the raw-HTML naming and
  persist-before-parse behavior is the pattern the crawler generalizes.
- **Conflict / coordinate with:** FEATURE-002 — M1's local layout is deliberately the same path
  shape and the same table names FEATURE-002 defines for S3. If that plan's layout changes, task 4.1
  changes with it.
- **Conflict / coordinate with:** `PropertyListing` changes shape (drops `price_per_sqm`, gains
  `operation`, `municipality`, `extraction_version`, `missing_fields`). No consumer exists outside
  this repository, so no migration is required — but `tests/test_idealista_listing_parser.py` and
  `src/scrape_listing_zenrows.py` both touch it.

## Technical-plan readiness

- **Artifact:** `dev/plans/technical/FEATURE-001-technical-plan.yaml`
- **Tasks:** 20; dependency graph acyclic and critical path verified yes
- **TDD contract:** RED failures and commands verified yes — the discovery command was reproduced in
  an isolated copy of the repository, including the state after task 0.2
- **File boundaries:** create/modify paths contained in allowed files; overlaps absent yes
- **Git workflow:** base, integration, task ancestry, and publish policy unambiguous yes
- **Required checks:** `workflow-consistency` only — the sole gate that exists and is accepted by
  `validate_workflow.py` without inventing CI configuration (see L3)

## Approval criteria

- **Blockers (must fix):** none
- **Required dispositions:** M1 **fixed** (output contract in task 4.1) · M2 **fixed** (monthly
  ledger in task 2.3) · M3 **fixed** (fixture decoupled from the live spike, tasks 0.3/1.3/1.4) ·
  M4 **fixed** (positive validity check, task 1.4) · M5 **fixed** (attempt ledger, task 3.3) ·
  M6 **fixed** (sequential fetching, task 2.1) · M7 **fixed** (README first, task 0.1) ·
  M8 **fixed** (per-page crawl unit in tasks 3.1/3.2, page-order priority in 3.4, sort question in
  0.3) · M9 **fixed** (district targets and `expected_listings` in task 4.2, discovery procedure
  documented in task 0.1)
- **Optional:** L1 **confirmed by evidence**, assertion kept in task 1.3 · L2 folded into task 0.3 ·
  L3 reflected in `validation.required_checks` · L4 resolved by this review's existence ·
  L5 folded into tasks 1.1 and 1.3 (raw `freshness_label` on the observation)
- **Accepted residual risk:** the detail-once rule keeps a stale detail record if a listing is edited
  after publication — accepted by the user, with `observed_at` and `extraction_version` recorded so a
  targeted re-fetch remains possible. Task 0.3 makes live requests and spends ~100 of 5,000 monthly
  credits; it is the only task that touches the network and requires the user's go-ahead.
- **Technical plan:** emitted, and updated on 2026-09-19 for M8 and M9

## Next step

Run `@implementer Implement FEATURE-001`. Task 0.3 spends live credits — get the user's explicit
go-ahead before executing it, and note that tasks 0.1, 0.2 and all of Phase 1 can proceed without it
once a search-page fixture exists from either source.

Nothing further is needed from the user before implementation starts.
