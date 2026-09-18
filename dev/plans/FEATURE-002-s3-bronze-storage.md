# FEATURE-002 — Bronze persistence of listing data in S3

**Status:** 🔵 Planned · **Effort:** M (~5h) · **Priority:** High
**Branch root:** `feature/s3-bronze-storage` · **Created:** 2026-09-18 · **Updated:** 2026-09-18

> Authored by `@architect`. Reviewed by `@reviewer` (see `dev/reviews/REVIEW-FEATURE-002.md`).
> Implemented by `@implementer` from `dev/plans/technical/FEATURE-002-technical-plan.yaml`.

## Objective

Store the results of a crawl run immutably and replayably in S3: raw HTML compressed, the weekly
observation table and the detail table as partitioned Parquet, plus the run report and quarantine —
such that a repeated run on the same day creates no duplicates and queries read only the partitions
they need.

## Context

- **Current state:** after FEATURE-001 the crawl writes raw HTML and records to `data/` only.
  `infra/` contains empty folders (`bootstrap/`, `envs/dev`, `envs/prod`, `modules/`, `shared/`).
  Not a single Terraform resource exists in this repository yet.
- **Reusable from the sibling project** `vlc-market-pulse/infrastructure` (inspected 2026-09-18):
  Terraform `>= 1.2, < 2.0`, AWS provider `>= 5.0, < 6.0`, region **eu-central-1**, the existing
  state bucket `vlc-real-estate-analytics-tf-state` with versioning, AES256 and `use_lockfile = true`
  (no DynamoDB lock table needed), plus the pattern from `modules/s3` (public access block, SSE,
  tagging, commented lifecycle rules).
- **Problem:** local files are neither durable, nor usable from a container run (FEATURE-003), nor
  queryable. Without a defined layout and partitioning we would create exactly the ad-hoc folder
  structure the repository rules rule out.
- **Constraints:** the budget is minimal; no recurring fixed cost for a catalog or compute. Raw
  observations must stay immutable and replayable. No personal data in Bronze.

## Scope

- **In scope:** the S3 bucket as a Terraform module, object layout and partitioning, Parquet
  serialization, gzipped raw HTML, quarantine and report storage, a sink abstraction with a local and
  an S3 implementation, lifecycle rules, encryption and public access block.
- **Out of scope:** Silver/Gold, Apache Iceberg, Glue catalog, Athena workgroup, the crawler itself,
  container and scheduling (FEATURE-003), cross-account access, bucket replication, the `prod`
  environment.
- **Users / consumers:** the crawl run as a writer; DuckDB or pandas locally as a reader.

## Decided constraints

Decided on 2026-09-18, confirmed by the user:

1. **Bucket name `<env>-vlc-market-oracle-lake`**, concretely `dev-vlc-market-oracle-lake`. It
   follows the sibling project's naming convention and keeps the two projects clearly separated
   inside the same account.
2. **`dev` only.** A `prod` environment without a running scheduler would be an empty bucket with
   maintenance overhead. `prod` arrives with FEATURE-003, once there is something to operate.
3. **Same AWS account as `vlc-market-pulse`.** The state bucket
   `vlc-real-estate-analytics-tf-state` is reused with its own key prefix `vlc-market-oracle/`. A
   second account would need its own bootstrapping for no discernible benefit.

## Dependencies

- **Needs:** FEATURE-001 — provides `ListingObservation`, `ListingDetail` and `CrawlReport` as
  stable records.
- **Unblocks:** FEATURE-003 — the container needs a target and a matching IAM policy.

## Open assumptions

None that are externally uncertain. The Parquet round trip, the partition paths and the idempotency
of object keys are deterministic and fully covered by unit tests; an additional spike would only
duplicate test code.

## Design

- **Primary approach:** a thin sink layer that separates pure serialization (key building, Parquet
  bytes, gzip) from storage (local filesystem or S3). The crawler only knows the `BronzeSink`
  protocol.

- **Object layout — two tables with different purposes:**

  ```
  s3://dev-vlc-market-oracle-lake/
    bronze/idealista/raw_html/operation=<sale|rent>/observed_date=YYYY-MM-DD/<listing_id>.html.gz
    bronze/idealista/listing_observations/operation=<sale|rent>/observed_date=YYYY-MM-DD/<target>.parquet
    bronze/idealista/listing_details/operation=<sale|rent>/observed_date=YYYY-MM-DD/<target>.parquet
    bronze/idealista/quarantine/observed_date=YYYY-MM-DD/<listing_id>.html.gz
    bronze/idealista/quarantine/observed_date=YYYY-MM-DD/<listing_id>.json
    bronze/idealista/runs/observed_date=YYYY-MM-DD/<run_id>.json
  ```

  - **`listing_observations`** — narrow, weekly, one row per listing and observation day. This table
    is what later answers how long a listing was online and when its price changed. Bronze stores
    the observation only; `first_seen`, `last_seen` and `days_on_market` are produced in Silver so
    that facts and derivations stay separate.
  - **`listing_details`** — wide, written **once per listing id** when the id is first seen, holding
    the full attribute set for deeper analysis. Not a time series: the only moving value is the
    price, and that lives in the observation table. Joined via `listing_id`.
    Joined via `listing_id`.

- **Partitioning and rationale:** Hive-style `operation=…/observed_date=…`.
  - `operation` separates two sets that are never analysed together and has exactly two values.
  - `observed_date` is the time axis of any later historization and enables partition pruning. For
    `listing_observations` it is also the key of the time series — a duration query reads exactly
    the weeks it needs.
  - Weekly observations and write-once details produce ~60 partitions per year of a few hundred KB
    each — deliberately **no** finer partitioning by district, to avoid the small-file problem.
    `municipality` and `district` stay columns, not partitions.
  - The layout is Hive-compatible and can therefore migrate to Iceberg later without copying data.

- **Contracts and invariants:**
  - Object keys are **deterministic**, derived from `(dataset, operation, observed_date,
    id/target)`. A second run on the same day overwrites the same objects — idempotency without
    dedup logic.
  - Raw HTML is written **before** the derived records; an abort afterwards can be fully repeated
    from Bronze.
  - The Parquet schema is declared explicitly (not inferred from pandas) and includes
    `extraction_version` and `observed_at` as a UTC timestamp.
  - Money is `int64` in euros; no float prices. Derived metrics belong in Silver, not Bronze.
  - Schema evolution is additive only, new fields nullable. A non-additive change increments
    `extraction_version`.

- **OOP / SOLID:** `BronzeSink` as a narrow `Protocol` (DIP) with two implementations —
  `LocalBronzeSink` (debugging, local runs) and `S3BronzeSink`. Two real variants justify the
  abstraction. Key building and Parquet serialization stay **pure functions**. No inheritance, and no
  repository class with a read path while we only write.
- **Patterns:** *Dependency Injection* of the sink; a Strategy emerges implicitly from the two
  implementations but is not built as a separate construct.
- **Deliberately rejected complexity:** no Glue catalog and no Athena resources (DuckDB locally is
  enough), no `moto` test dependency (an injected `put_object` callable instead), no bucket
  versioning for Bronze (keys are deterministic and the data immutable), no KMS CMK (SSE-S3 is
  sufficient and saves $1/month per key), no DynamoDB lock table.

## Approach

### Phase 1 — Serialization and keys
- [ ] **RED:** `test_bronze_keys.py` — `build_object_key` produces exactly the documented paths for
      observation, detail, raw HTML, quarantine and report; identical input produces an identical
      key. Expected failure: `ModuleNotFoundError`. **GREEN/REFACTOR.**
- [ ] **RED:** `test_bronze_serialization.py` — `records_to_parquet` returns bytes that can be read
      back with the declared schema; `None` fields stay `null`; a record with an unknown field
      raises a specific error instead of silent schema drift. **GREEN:** pyarrow-based
      serialization. **REFACTOR.**
- [ ] **RED:** a test for gzipped raw HTML — the round trip returns exactly the original.
      **GREEN/REFACTOR.**

### Phase 2 — Sinks
- [ ] **RED:** `test_local_bronze_sink.py` — writes into a `tmp_path`, creates the partition
      directories, and a second run creates no additional files. **GREEN/REFACTOR.**
- [ ] **RED:** `test_s3_bronze_sink.py` with a `FakeObjectStore` (records `put_object` calls) —
      expects bucket, key, `ContentType`, `ContentEncoding: gzip` for raw HTML, and the exact number
      of calls; a write failure propagates with key context. **GREEN:** `S3BronzeSink` with an
      injected client. **REFACTOR.**
- [ ] **RED:** an integration test through `FakeObjectStore` — a complete `CrawlReport` from
      FEATURE-001 produces exactly the expected set of objects. **GREEN/REFACTOR.**

### Phase 3 — Infrastructure
- [ ] Validation first: write `infra/modules/lake_bucket`, run `terraform fmt -check`,
      `terraform validate` and `terraform plan` against `envs/dev`, and review the plan before
      anything is applied. Bucket with SSE-S3, public access block and tags.
- [ ] Add lifecycle rules: `bronze/idealista/raw_html/` transitions to `GLACIER_IR` after 90 days
      and to `DEEP_ARCHIVE` after 365 days; abort incomplete multipart uploads after 7 days. Parquet
      stays in `STANDARD`. Review the plan again.
- [ ] `infra/envs/dev` with `backend.tf` (state bucket `vlc-real-estate-analytics-tf-state`, key
      `vlc-market-oracle/dev/terraform.tfstate`, region `eu-central-1`, `use_lockfile = true`),
      `providers.tf`, `variables.tf`, `main.tf` and `outputs.tf`. `prod` follows with FEATURE-003.
- [ ] Add `--sink local|s3` and `--bucket` to the CLI; the local default stays `local`. Document the
      layout, partitioning and lifecycle in the README.

## Files

- **Create:**
  - `src/storage/bronze_keys.py` — deterministic object keys.
  - `src/storage/bronze_serialization.py` — Parquet schema and gzip.
  - `src/storage/bronze_sink.py` — `BronzeSink` protocol, `LocalBronzeSink`, `S3BronzeSink`.
  - `infra/modules/lake_bucket/{main,variables,outputs}.tf`
  - `infra/envs/dev/{backend,providers,variables,main,outputs}.tf`
- **Change:** `src/collect_region.py` (sink selection), `requirements.txt` (`pyarrow`, `boto3`),
  `README.md` (bronze layout, partitioning, Terraform commands).
- **Tests:** `tests/test_bronze_keys.py`, `tests/test_bronze_serialization.py`,
  `tests/test_local_bronze_sink.py`, `tests/test_s3_bronze_sink.py`.

## Test strategy

- **Unit:** key building per record type, Parquet schema fidelity, `None` handling, gzip round trip,
  error context on write.
- **Contract / fixtures:** a small set of synthetic observations and detail records, including one
  record with many `None` fields and one additively extended schema.
- **Integration:** a complete report mapped to the expected object set through `FakeObjectStore`.
- **Retries / idempotency / evolution:** a second run with identical input produces identical keys
  and no additional objects; an additive schema extension stays readable.
- **Configured quality checks:** `python -m unittest discover -s tests -t . -v`,
  `python dev/tools/validate_workflow.py`, plus `terraform fmt -check` and `terraform validate` in
  `infra/envs/*` (the new CI check `terraform-validate`, already allowed by
  `dev/tools/validate_workflow.py`).
- **Manual:** review `terraform plan` once; then a real test run with
  `--max-listings 10 --sink s3` against `dev` and a visual check of the object keys.

## Operational and compliance impact

- **Scraping / legal:** N/A — this feature issues no requests.
- **Privacy / security:** the bucket blocks all public access, SSE-S3 at rest, TLS in transit. No
  agent or contact data in Bronze. The writer later receives only `s3:PutObject` on
  `bronze/idealista/*` (FEATURE-003), never `s3:Delete*`.
- **Observability:** the run report under `runs/` is the primary operational artifact (object count,
  bytes, errors, coverage). Never log payload content.
- **Failure and recovery:** write failures propagate with key context; because keys are
  deterministic, a rerun is safe. Raw HTML in Bronze allows full reparsing without spending new
  ZenRows credits.
- **Migration / compatibility:** no existing data in S3. Local runs stay possible through
  `LocalBronzeSink`.

## Estimated monthly cloud cost

Assumptions: region eu-central-1, starting scope L'Eliana with ~360 listings; weekly observations,
detail pages written once per listing id (~25 new ids per month after the backfill); raw HTML 206 KB
→ gzip ~30 KB; observation Parquet ~25 KB per week, detail Parquet a few hundred KB in total.

| Component | Pricing basis | Assumption | Est. / month |
|---|---|---|---|
| S3 Standard (storage) | $0.0245 / GB-month | ~11 MB backfill + ~1 MB per month | ~$0.00 |
| S3 PUT/COPY/POST | $0.0054 / 1,000 requests | ~80 PUTs per month | ~$0.00 |
| S3 GET (local analysis) | $0.00043 / 1,000 requests | ~2,000 GETs per month | ~$0.00 |
| **Total (new AWS components)** | | | **< $0.01/month** |

- **Cost drivers & cheaper alternatives:** at the starting scope the bucket is effectively free.
  Storage only becomes relevant when expanding to all of Valencia city: ~0.4 GB of raw HTML per full
  pass, roughly $0.30/month after a year — which is what the Glacier IR and Deep Archive lifecycle
  rules are for. The only cheaper option would be dropping raw HTML, which would sacrifice
  replayability and is deliberately rejected. No data transfer cost arises as long as writer and
  bucket share a region.
- **External / non-AWS costs:** none (ZenRows credits are tracked in FEATURE-001).
- **Budget check:** yes, negligible.

## Success criteria

- [ ] A run writes raw HTML, `listing_observations`, `listing_details`, quarantine and the report
      under the documented partition paths.
- [ ] A second run with identical input produces identical keys and no duplicates.
- [ ] Parquet is readable with the declared schema; a DuckDB query filtered on `observed_date`
      provably reads only the filtered partition.
- [ ] `terraform validate` and `terraform fmt -check` pass; the bucket blocks public access and is
      encrypted.
- [ ] Every behavior was implemented test-first, with no new test dependency on real AWS endpoints.

## Open questions & risks

- **Risk:** `pyarrow` is a large wheel (~40 MB) and will grow the container image later.
  *Mitigation:* acceptable; the alternative, NDJSON instead of Parquet, worsens queryability and
  compression.
- **Risk:** raw HTML can contain agent contact data. *Mitigation:* Bronze stays private, derived
  records do not carry those fields, and no raw HTML fixture enters the repository unredacted.
- **Risk:** the bucket name may already be taken globally. *Mitigation:* `terraform plan` shows this
  before the apply; fall back to a name with an account suffix.
- **Assumption:** writing and reading both happen in eu-central-1, so no egress is billed.

## Progress log

- **2026-09-18** — Plan created; Terraform conventions and reusable patterns adopted from
  `vlc-market-pulse/infrastructure`.
- **2026-09-18** — Open questions decided: bucket `dev-vlc-market-oracle-lake`, `dev` only, same AWS
  account with the reused state bucket.
- **2026-09-18** — User feedback: the datasets are now named `listing_observations` (weekly, the
  basis for listing duration and price history) and `listing_details` (full attribute set); volumes
  rescaled to the smaller starting scope.
- **2026-09-18** — Starting scope narrowed to L'Eliana only (~360 listings) and `listing_details`
  changed to write-once per listing id, because the search card already carries price, previous
  price and drop percentage. Volumes and partition counts re-estimated accordingly.
