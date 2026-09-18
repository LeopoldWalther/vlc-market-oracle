# VLC Market Oracle - Copilot Instructions

## Mission and Scope

Build a trustworthy real-estate data platform for Valencia and, later, the wider Comunidad Valenciana. Collect listing snapshots from property portals, starting with Idealista, and expose
clean, historized data through an Apache Iceberg lakehouse.

The data platform is the product foundation. Current candidate use cases are:

1. fair-price estimation and over-/under-pricing detection;
2. fix-and-flip renovation arbitrage;
3. buy-to-let yield maps;
4. listing liquidity and time-on-market prediction;
5. market-dynamics and gentrification analysis.

Treat these as roadmap options, not settled requirements. Keep ingestion and data models reusable
until a use case is explicitly selected.

## Ground Truth and Priorities

- Write every repository artifact in English: code, comments, docstrings, documentation, plans,
    reviews, configuration, and commit messages. Chat with the user may be in another language, but
    nothing written into the repository is.
- This repository is evolving. Inspect the current code, tests, plans, and configuration before
    changing anything; do not describe planned components as already implemented.
- Resolve conflicts in this order: correctness and data integrity, legal/ethical collection,
    simplicity and readability, maintainability, then performance.
- Make the smallest coherent change that satisfies the requirement. Do not add speculative
    features, generic frameworks, compatibility layers, or abstractions for hypothetical reuse.
- Preserve public contracts unless the task explicitly changes them. State assumptions when the
    repository does not establish a decision.

## Target Architecture

Keep dependencies directed through these conceptual boundaries:

1. **Source adapters** fetch portal pages or responses and retain source-specific details.
2. **Extraction** converts source payloads into explicit listing snapshots without losing raw
     provenance.
3. **Bronze** stores immutable raw observations and ingestion metadata.
4. **Silver** validates, normalizes, deduplicates, and historizes listings in Apache Iceberg.
5. **Gold** publishes use-case-specific features, aggregates, and training datasets.
6. **Consumers** query curated data; dashboards and models must not depend on scraper internals.

Raw observations must remain replayable. Every derived record must be traceable to its source,
listing identifier, source event time when available, ingestion time, and transformation version.
Do not couple the core domain model to Idealista: portal-specific selectors, URLs, and payload rules
belong behind a source adapter.

## Mandatory TDD Workflow

Use red-green-refactor for every behavior change:

1. **Red:** add or change the smallest test that specifies the behavior, then run it and confirm it
     fails for the expected reason. For a bug, first add a regression test that reproduces it.
2. **Green:** write only enough production code to pass that test.
3. **Refactor:** improve names and structure only while tests stay green.
4. Run the narrowest relevant test after each edit, then the affected suite before finishing.

Do not write production behavior first and backfill tests. If no test harness exists, establish the smallest suitable harness as the first slice. Tests must be deterministic, behavior-focused, and independent of execution order. Mock or fake network, clock, randomness, object storage, catalog, and other paid or unreliable boundaries in unit tests. Use small recorded HTML/JSON fixtures for parsers and controlled local resources for integration tests; never scrape a live portal in the
default test suite. Test outcomes and contracts, not private implementation details. Cover the happy path, malformed or missing source fields, boundary values, retries/idempotency, and schema evolution where relevant. Do not weaken assertions or delete coverage merely to make a test pass.

## Simple, Clean Code

- Prefer the simplest readable implementation. A short pure function is better than a class when no state, lifecycle, interchangeable behavior, or dependency boundary exists.
- Give each module, class, and function one clear responsibility. Keep functions short enough to understand at a glance, but do not split cohesive logic to satisfy an arbitrary line count.
- Use domain names such as `listing_snapshot`, `asking_price`, and `observed_at`; avoid vague names such as `data`, `manager`, `helper`, or `utils` when a precise name is available.
- Use explicit types at public and architectural boundaries. Avoid `Any` and unstructured dictionaries for stable domain records. Prefer immutable value objects for validated records.
- Write docstrings for public APIs and non-obvious contracts. Do not repeat the signature in prose. Comments explain why a decision or invariant exists, never narrate obvious code.
- Validate at system boundaries and fail with specific, actionable exceptions. Never silently drop malformed records or catch broad exceptions without adding context and preserving the cause.
- Pass configuration explicitly. Keep secrets out of source code, fixtures, logs, and notebooks.
- Add a dependency only when the standard library or an existing dependency cannot solve the need clearly. Explain and test the new boundary.
- Remove duplication only after the shared concept is clear. Three obvious lines are often better than a premature abstraction.

## OOP, SOLID, and Design Patterns

Use OOP and SOLID as design tests, not as requirements to maximize classes or interfaces.

- **Encapsulation:** objects protect real invariants and expose small, intention-revealing APIs.
- **Abstraction:** introduce an interface at an external boundary or where multiple implementations actually exist or are required by the current task.
- **Inheritance:** use only for a genuine substitutable is-a relationship. Prefer composition.
- **Polymorphism:** use it when callers must treat real variants uniformly, such as portal adapters.
- **SRP:** separate fetching, parsing, normalization, persistence, orchestration, and analytics.
- **OCP/LSP:** add variants through stable contracts and keep every implementation behaviorally substitutable; do not distort a model merely to claim extensibility.
- **ISP:** expose narrow consumer-specific protocols rather than broad service interfaces.
- **DIP:** core logic depends on domain-level protocols; inject network, clock, storage, Iceberg catalog, and model-serving implementations at the composition root.

Apply a named pattern only when it removes present duplication or coupling. Likely useful patterns are **Adapter** for property portals, **Strategy** for genuinely variable extraction or validation, **Repository** for Iceberg-backed access, and **Dependency Injection** at external boundaries. Use a Factory or Template Method only when concrete variants already justify it. Never add inheritance, an interface, or a pattern solely to demonstrate a principle.

## Data and Lakehouse Rules

- Define and test schemas and partition evolution deliberately; use Iceberg features instead of hand-built folder conventions or overwrite-based table management.
- Make ingestion idempotent. A retry must not create duplicate observations or corrupt table state.
- Preserve temporal meaning: distinguish source publication/update time, observation time, and ingestion time; store timestamps in UTC and convert only at presentation boundaries.
- Represent currency and measurements without binary floating-point surprises. Record currency and units explicitly; normalize only with documented rules.
- Treat listing disappearance as an observation-derived state, not proof of a completed sale or rental. Keep facts separate from inferred labels.
- Version transformations and ML datasets. Prevent target leakage by respecting observation time in training and evaluation splits.
- Minimize collection of personal data. Do not expose raw personal information in logs, fixtures, analytics tables, or model features.

## Scraping Rules

- Collect only publicly reachable pages. Do not bypass authentication or access controls, and do not access data that requires an account, a paid subscription, or a private API you are not entitled to use.
- Anti-bot mitigation is allowed for public pages: managed scraping APIs, residential proxies, real browser engines, realistic headers, and human-like pacing are acceptable tools. Prefer a managed provider over hand-built fingerprint spoofing, and keep the chosen mechanism configurable and documented.
- Respect applicable law, portal terms, and configured rate limits. Keep request volume modest enough that it does not degrade the portal's service, and stop collection from a source if the operator objects.
- Use bounded retries with backoff and jitter only for transient failures. Set explicit timeouts and identify the collector as required by the approved access policy.
- Keep HTTP acquisition separate from deterministic parsing so parsers can be tested from fixtures.
- Detect layout/schema drift visibly. Quarantine invalid payloads with provenance and diagnostics instead of silently emitting partial data.
- Log operational metadata, counts, latency, and error categories; never log secrets or unnecessary page content and personal data.

## Infrastructure and Operations

- Define cloud resources as code under `infra/`; keep `dev` and `prod` configuration explicit and avoid manual environment drift.
- Apply least privilege, encryption in transit and at rest, lifecycle policies, bounded concurrency, and cost controls. Any feature that changes cloud resources must document expected monthly cost, assumptions, dominant cost drivers, and a cheaper alternative.
- Design jobs to be observable and safe to retry. Emit structured logs and metrics at external and data-quality boundaries, not for every internal function call.
- Notebooks are for exploration, not production pipelines. Move reusable, tested behavior into importable modules under `src/`.

## Repository Workflow

- For non-trivial features, use the Architect -> Reviewer -> Implementer workflow documented in `dev/plans/README.md`. Plans belong in `dev/plans/`, reviews in `dev/reviews/`, and executable technical plans in `dev/plans/technical/`.
- Build each implementation task as an independently testable TDD slice. Keep changes focused; do not mix feature work with unrelated refactors or formatting.
- Follow the existing branch conventions in `dev/plans/README.md`. Do not create branches, commit, push, or change feature status unless the user requests it or the active workflow requires it.
- Discover commands from repository configuration instead of inventing them. After changing workflow artifacts, run `python dev/tools/validate_workflow.py`.

## Definition of Done

A change is complete only when:

- the requested behavior is covered by a test that failed first and now passes;
- focused tests and the affected broader suite pass;
- types, linting, and formatting pass when configured;
- data contracts, migrations, operational behavior, and costs are documented when affected;
- no secrets, generated clutter, unrelated refactors, or accidental data files are included;
- the final response reports what changed, the exact validation performed, and any remaining risk.
