# FEATURE-003 — Scheduled collection run as a container on AWS Fargate

**Status:** 🔵 Planned · **Effort:** M (~6h) · **Priority:** Medium
**Branch root:** `feature/scheduled-container-run` · **Created:** 2026-09-18 · **Updated:** 2026-09-18

> Authored by `@architect`. Reviewed by `@reviewer` (see `dev/reviews/REVIEW-FEATURE-003.md`).
> Implemented by `@implementer` from `dev/plans/technical/FEATURE-003-technical-plan.yaml`.

## Objective

Run the crawl regularly in AWS without manual intervention: as a container image on ECS Fargate,
triggered by EventBridge Scheduler, with the ZenRows key from SSM Parameter Store, write access
limited to the bronze prefix, and an email on failure — while the local workflow stays essentially
unchanged.

## Context

- **Current state:** after FEATURE-001 and FEATURE-002 a CLI run exists that writes locally or to
  S3. In AWS this repository so far owns only the bronze bucket from FEATURE-002. The account
  already contains, from `vlc-market-pulse`, a Terraform state bucket, an **account-wide** GitHub
  OIDC provider, and reusable patterns for SNS and secrets.
- **Problem:** a manually started run on the laptop does not produce a reliable time series. A
  missed month leaves a gap that cannot be filled later — Idealista only shows the current state.
- **Constraints:** the run exceeds Lambda's 15-minute limit, so Fargate is both the user's choice
  and the technically appropriate one. Cost should stay in the low single-digit dollar range. The
  ZenRows key must not enter the image or the logs.

## Scope

- **In scope:** Dockerfile, ECR repository with an image lifecycle, ECS cluster and Fargate task
  definition, **two** EventBridge Scheduler schedules (weekly search pages only, monthly search
  pages plus detail pages), least-privilege IAM roles, an SSM parameter for the ZenRows key, a
  CloudWatch log group with retention, an SNS notification on task failure, a GitHub Actions
  workflow for build and push, the `prod` environment, and documentation of the manual ad-hoc start.
- **Out of scope:** CI/CD for `terraform apply` (stays manual), Step Functions orchestration,
  Silver/Gold jobs, autoscaling, a new VPC, monitoring beyond the failure email.
- **Users / consumers:** the operator; results land in Bronze (FEATURE-002).

## Decided constraints

Decided on 2026-09-18, confirmed by the user:

1. **Two schedules, one task definition.** Weekly `cron(0 3 ? * MON *)` with `--cards-only`, monthly
   `cron(0 4 1 * ? *)` without restriction (both UTC). They differ only through a command override —
   no second image, no second definition. Rationale: a purely monthly run loses price changes and
   short-lived listings; search pages are the cheap part, so running them weekly costs nothing extra
   on the AWS side.
2. **SSM Parameter Store (`SecureString`) instead of Secrets Manager.** It saves $0.40/month, which
   was the single largest item in the entire AWS budget. ECS injects SSM parameters through the same
   `secrets` field of the task definition, and since neither automatic rotation nor cross-account
   sharing is needed, there is no functional difference here.
3. **Same AWS account as `vlc-market-pulse`.** The account-wide GitHub OIDC provider and the
   Terraform state bucket are reused; only a repository-specific role is new.
4. **`prod` is created here**, together with the scheduler — before that there would be nothing to
   operate. `dev` keeps a disabled scheduler and serves the manual test run.

## Dependencies

- **Needs:** FEATURE-001 (a run entry point with limits and exit codes), FEATURE-002 (bucket and
  sink).
- **Unblocks:** later Silver/Gold processing that relies on regular Bronze deliveries.

## Open assumptions

No open data or algorithm assumption — this wires up known infrastructure. The risky parts (IAM,
networking, scheduler) are validated with `terraform plan` and a single manual `RunTask`, not with a
spike.

## Design

- **Primary approach:** a single container image that runs the same CLI entry point as the local
  workflow. Everything behavior-relevant arrives through environment variables and CLI arguments in
  the task definition — there is no separate "cloud code path" that could not be tested locally.

- **Boundaries and data flow:**

  ```
  EventBridge Scheduler (weekly, --cards-only) ─┐
  EventBridge Scheduler (monthly, full)  ───────┤
                    │ RunTask
                    ▼
              ECS Fargate task ──► ZenRows ──► Idealista
                    │
                    ├──► S3 bronze/ (task role, PutObject only)
                    ├──► SSM Parameter Store (read ZENROWS_API_KEY only)
                    └──► CloudWatch Logs
  ECS task state change (exit != 0) ──► EventBridge rule ──► SNS ──► email
  ```

- **Networking — the most important cost decision:** the task runs in **public subnets of the
  default VPC** with `assign_public_ip = true` and a security group that only allows egress. This
  removes the need for a NAT gateway. A NAT gateway would cost **~$38/month** and would exceed the
  actual compute cost by more than fiftyfold. Ingress is fully blocked; the task is not a server.

- **Contracts and invariants:**
  - The image runs `python -m src.collect_region`; configuration comes only from env and arguments.
  - Exit code 0 means the run succeeded and coverage thresholds held; non-zero raises an alert.
  - A second run on the same day is safe (deterministic keys from FEATURE-002).
  - `stopTimeout` and a hard credit budget bound runtime and spend.
  - The secret value is injected by ECS and never appears in the task definition, logs or image.

- **OOP / SOLID:** no new application code beyond a small configuration resolution that translates
  environment variables into the existing parameters — a pure function. Deliberately **no** `Runner`
  or `Job` class and no Template Method; there is only one execution variant.
- **Patterns:** none.
- **Deliberately rejected complexity:** no custom VPC with private subnets and NAT, no Step
  Functions, no Fargate Spot (an interruption mid-run burns credits), no ECS service (the task is
  finite), no automation of `terraform apply`, no custom monitoring dashboard.

## Approach

### Phase 1 — A runnable image
- [ ] **RED:** `test_container_entrypoint.py` — the configuration resolution translates
      `COLLECT_TARGETS`, `MAX_LISTINGS`, `CREDIT_BUDGET` and `BRONZE_BUCKET` into the expected
      parameters; missing required variables raise a specific error; a failed run yields a non-zero
      exit code. **GREEN/REFACTOR.**
- [ ] Validation first: a `Dockerfile` on `python:3.12-slim` with a non-root user, installing only
      `requirements.txt`, without Playwright or Chrome. Build locally, run with
      `--max-listings 5 --replay`, and measure the image size.

### Phase 2 — Infrastructure
- [ ] Validation first: write `infra/modules/collector_task` — ECR repository (lifecycle: keep the
      last 5 images), ECS cluster, task definition (0.5 vCPU, 1 GB, ARM64), log group with 30-day
      retention. Review `terraform fmt -check`, `validate` and `plan`.
- [ ] Least-privilege IAM: execution role (ECR pull, logs, `ssm:GetParameters` on exactly one
      parameter, `kms:Decrypt` on the AWS-managed SSM key), task role (`s3:PutObject` restricted to
      `arn:aws:s3:::<bucket>/bronze/idealista/*`, **no** `s3:Delete*`, **no** `s3:*`). Review the
      plan and read the policy documents.
- [ ] Create the SSM parameter `/vlc-market-oracle/<env>/zenrows-api-key` as a `SecureString`. Its
      value is set **outside** Terraform (`aws ssm put-parameter`) so it never enters the state;
      Terraform manages only the reference and ignores `value` via `lifecycle`.
- [ ] Two EventBridge schedules with a `RunTask` target sharing one task definition: weekly
      `cron(0 3 ? * MON *)` with the command override `--cards-only`, monthly `cron(0 4 1 * ? *)`
      without an override. Schedules as variables, `flexible_time_window` off, both disabled in
      `dev`.
- [ ] SNS topic plus an EventBridge rule on `ECS Task State Change` filtered on
      `containers.exitCode != 0` → email. Adopt the pattern from `vlc-market-pulse/modules/sns`.
- [ ] Run `aws ecs run-task` manually once with `MAX_LISTINGS=10`, check logs, the written S3 keys
      and the exit code. Only then enable the schedulers.

### Phase 3 — Delivery and documentation
- [ ] GitHub Actions workflow: build and push to ECR through OIDC. Reference the **existing**
      account-wide OIDC provider with a `data` source — creating another
      `aws_iam_openid_connect_provider` fails with `EntityAlreadyExists`. Add only a new role for
      this repository.
- [ ] README: the schedules, the manual ad-hoc start, the kill switch (disable the scheduler or set
      the credit budget to 0), the cost overview, a note on the deliberate NAT-free networking, and
      the fact that the SSM parameter value is set manually.

## Files

- **Create:** `Dockerfile`, `.dockerignore`, `src/container_config.py`,
  `infra/modules/collector_task/{main,variables,outputs}.tf`,
  `infra/modules/scheduler/{main,variables,outputs}.tf`,
  `infra/modules/alerts/{main,variables,outputs}.tf`,
  `infra/modules/api_key_parameter/{main,variables,outputs}.tf` (SSM `SecureString`, value set
  outside Terraform), `infra/envs/prod/{backend,providers,variables,main,outputs}.tf`,
  `infra/shared/github-actions-role/{main,variables,outputs,backend,providers}.tf`,
  `.github/workflows/build-and-push.yml`, `tests/test_container_entrypoint.py`
- **Change:** `infra/envs/dev/main.tf` (new modules, scheduler disabled), `README.md` (operations
  section), `requirements.txt` if needed.
- **Tests:** `tests/test_container_entrypoint.py` — configuration resolution, required variables,
  exit code behavior.

## Test strategy

- **Unit:** env-to-parameter translation, missing and invalid variables, exit code mapping.
- **Contract / fixtures:** N/A beyond the configuration cases.
- **Integration:** a local container run in `--replay` mode (no requests, no credits) proving the
  image can execute the full path including the sink.
- **Retries / idempotency / evolution:** two consecutive manual task starts on the same day produce
  no duplicate objects.
- **Configured quality checks:** `python -m unittest discover -s tests -t . -v`,
  `python dev/tools/validate_workflow.py`, `terraform fmt -check`, `terraform validate` (CI check
  `terraform-validate`).
- **Manual:** a single `aws ecs run-task` with a tight limit; check logs, S3 keys, exit code and the
  failure email (from a deliberately provoked failure).

## Operational and compliance impact

- **Scraping / legal:** the schedule determines the load on the portal. Weekly search pages and a
  monthly detail run with bounded concurrency is moderate. Kill switch: disable the scheduler or set
  the credit budget to 0.
- **Privacy / security:** the key is injected from SSM at runtime only, never in the image, the
  Terraform state or the logs; log group with retention; task role without delete permissions;
  security group without ingress; no reachability from outside because no ports are opened.
- **Observability:** CloudWatch logs of the run, the run report in S3, an SNS email on a non-zero
  exit. A missing delivery is visible through the report prefix in S3.
- **Failure and recovery:** `stopTimeout` bounds a hanging run; a failed run is **not** retried
  automatically (credits!) but restarted manually after review.
- **Migration / compatibility:** there is no existing execution to migrate; the local path stays
  usable unchanged.

## Estimated monthly cloud cost

Assumptions: eu-central-1, one full run per month plus four search-page-only runs, ~77 ZenRows
requests per month (starting scope L'Eliana), concurrency 5; estimated runtime ~5 min (full run) and
~2 min each (search pages) ⇒ ~0.2 task hours per month. The cost model conservatively assumes
**2 task hours** so that it still holds after an expansion to several Valencia neighbourhoods.
Task 0.5 vCPU / 1 GB, image ~0.4 GB.

| Component | Pricing basis | Assumption | Est. / month |
|---|---|---|---|
| ECS Fargate (x86) | $0.04656 / vCPU-h + $0.00511 / GB-h | 0.5 vCPU + 1 GB × 2 h | ~$0.06 |
| ECR storage | $0.10 / GB-month | ~0.4 GB (5 images via lifecycle) | ~$0.04 |
| SSM Parameter Store | free in the standard tier | 1 `SecureString` | $0.00 |
| CloudWatch Logs | $0.63 / GB ingest | ~30 MB | ~$0.02 |
| EventBridge Scheduler | 14M invocations/month free | 5 invocations | $0.00 |
| SNS (email) | 1,000 emails/month free | a few | $0.00 |
| Internet egress | first 100 GB/month free | a few MB | $0.00 |
| **Total (new AWS components)** | | | **~$0.12/month** |

- **Cost drivers & cheaper alternatives:** at this volume nothing dominates — the largest items are
  ECR storage and Fargate compute, both in cents. ARM64/Graviton instead of x86 cuts Fargate cost by
  a further ~20 %. **The real cost lever is ZenRows, not AWS.**
- **Deliberately avoided:** a NAT gateway (~$38/month + $0.052/GB) through public subnets; Secrets
  Manager ($0.40/month per secret) through SSM Parameter Store; a KMS CMK ($1/month per key) through
  SSE-S3 and the AWS-managed SSM key; a DynamoDB lock table through `use_lockfile`.
- **External / non-AWS costs:** the ZenRows plan — Build at €16/month for the starting scope (see
  FEATURE-001), billed separately.
- **Budget check:** yes — combined AWS cost for FEATURE-002 and FEATURE-003 is **~$0.13/month**.

## Success criteria

- [ ] The image runs the same CLI as the local workflow and is testable in replay mode without AWS.
- [ ] A manually started task with `MAX_LISTINGS=10` writes the expected objects under
      `bronze/idealista/` and exits with code 0.
- [ ] Both schedulers fire at the configured times; the weekly run provably issues no detail page
      requests.
- [ ] A deliberately provoked failure produces an SNS email.
- [ ] The task role provably allows only `PutObject` beneath `bronze/idealista/`.
- [ ] The ZenRows key appears in cleartext neither in the Terraform state, nor in the task
      definition, nor in the logs.
- [ ] `terraform validate`, `terraform fmt -check` and the test suite pass; no secrets in the
      repository.
- [ ] There is **no** NAT gateway in the plan.

## Open questions & risks

- **Risk:** the run takes longer than estimated and exhausts the credit budget mid-pass.
  *Mitigation:* the hard credit budget from FEATURE-001 stops it with a written partial report;
  Bronze stays consistent because raw HTML is written first.
- **Risk:** public subnets are mistaken for an insecure choice. *Mitigation:* security group without
  ingress, no ports, no services in the container — documented in the README.
- **Risk:** the default VPC may not exist in the target account. *Mitigation:* subnet and VPC ids as
  variables rather than a data source with an implicit assumption.
- **Risk:** the account-wide OIDC provider is accidentally recreated and the apply fails with
  `EntityAlreadyExists`. *Mitigation:* reference it explicitly as a `data` source; the reviewer
  checks this point specifically in the plan.
- **Assumption:** a monthly run stays well under an hour. Falsifiable on the first real run; the
  cost model would stay below $0.10 of compute even at three hours.

## Progress log

- **2026-09-18** — Plan created; the NAT-free networking recorded as the central cost decision;
  reuse of the existing account-wide GitHub OIDC provider noted.
- **2026-09-18** — Open questions decided: two schedules (search pages weekly, details monthly), SSM
  Parameter Store instead of Secrets Manager, same AWS account, `prod` created with this feature.
- **2026-09-18** — User confirmed Parameter Store and the shared account; the runtime assumption was
  adjusted to the smaller starting scope while the cost model still assumes 2 task hours.
- **2026-09-18** — Starting scope narrowed to L'Eliana only; the monthly run now fetches detail
  pages for previously unseen listing ids only, which further reduces runtime and ZenRows spend.
