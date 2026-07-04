# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Grafana dashboards as code, over the OSS Infinity datasource** (`terraform/05_grafana_content/`, ADR-010): the pipeline-observability dashboard (9 panels — stat / barchart / bargauge / timeseries / table over `pipeline_metrics`: join match rate, quarantine count, risk-score PSI/drift, band distribution, sensor null rates, plus per-run trends) is provisioned entirely in Terraform via the `grafana` provider — **no manual UI setup**. The official Databricks datasource plugin is Enterprise-only (+$45/active user/mo on AMG), so instead the free **Infinity** plugin POSTs SQL to the Databricks **SQL Statement Execution REST API** authenticated with **OAuth2 machine-to-machine** using the read-only BI SPN — so the dashboards respect the UC column masks by construction (no Art. 9 biometrics leave the platform). Layer 04 now also sets `pluginAdminEnabled`, mints an ADMIN **service-account token**, and installs the Infinity plugin via the Grafana HTTP API; layer 05 reads that token from remote state (avoiding the provider-bootstrap problem). Queries use Infinity's **backend** parser (server-side, so they also work for alerting; the frontend UQL parser does not). `data_analysts` were granted `USE_SCHEMA + SELECT` on `fleet_dev.metadata` so the BI SPN can read the metrics fact. `make grafana-up` / `grafana-down` wrap the two layers.
- **Amazon Managed Grafana via Terraform** (`terraform/04_grafana/` + `modules/aws_grafana/`): a standalone layer that provisions an AMG workspace (IAM Identity Center auth, a customer-managed workspace IAM role, and an SSO ADMIN role association) for operational monitoring of the `pipeline_metrics` fact over the Databricks SQL Warehouse. Isolated remote state so it can be created for a demo and torn down independently.
- **Destroy workflow** (`.github/workflows/destroy-infrastructure.yml`): a manual `workflow_dispatch` teardown with a **cumulative top-down scope** choice — *Unity Catalog only (03)* / *+ Workspace config (03→02)* / *Everything (03→02→01)* — always destroyed in reverse dependency order, so a lower layer is never torn down while a higher one depends on it. Guarded by a typed `confirm` = `destroy` input. For the full teardown it runs `bundle destroy` first (removing the DABs jobs while the workspace still exists), then the Terraform layers. New `destroy` action on `bundle.sh`.
- **Dedicated read-only BI Service Principal** (`grafana-bi-reader-<env>`) for Grafana/Streamlit, created in layer 01: **not** an account admin, it inherits exactly analyst-level read access (USE_CATALOG + USE_SCHEMA + SELECT on `fleet_dev.operations` + SQL-warehouse usage) purely by membership of the `data_analysts` group — no bespoke grants, no changes to layers 02/03. It is deliberately **not** in `fleet_safety_officers`, so the dashboards respect the GDPR masks (risk scores / alerts / coarse location shown; raw biometrics masked). Its OAuth secret is stored alongside the project SPN in Secrets Manager (`bi_reader_client_id` / `bi_reader_client_secret`), and its client id is exposed as the `bi_reader_application_id` output.
- **Auto-add the project SPN to the masking privileged group**: layer 01 now looks up the
  account-level `mask_privileged_group` (`fleet_safety_officers`) via a data source and adds the
  Terraform-created project SPN to it, so the pipeline's own observability reads (biometric
  null-rates) are not masked — no manual membership step. Human members stay managed by identity
  admins. The group must exist before the apply (a documented prerequisite; a missing group now
  fails loudly). New `mask_privileged_group` variable on layer 01 + the `databricks_account` module.
- **Prerequisites / bootstrap documentation + `TF_VAR_aws_account_id` wiring**: a new
  *Prerequisites (one-time bootstrap)* section in `CLAUDE.md` (and a pointer from `README.md`)
  lists everything a real run needs — accounts, the Terraform state bucket, the account-admin SPN,
  the `fleet_safety_officers` group, and the exact local `.env` values / GitHub secrets. The real
  AWS account id is now supplied via `TF_VAR_aws_account_id` — added to `.env.example` and wired
  into the deploy and PR-plan workflows from a new `AWS_ACCOUNT_ID` secret (the committed `.tf`
  default stays a placeholder).
- **One-click scenario runner** (`.github/workflows/run-fleet-pipeline.yml`): a manual `workflow_dispatch` with a **choice** dropdown — *"Simulated IoT sensors (mock data)"* vs *"Real vehicle telemetry (VED replay)"* — that maps the selection to the matching DABs job, deploys the current bundle, and runs it (no infrastructure re-apply; that stays in the deploy workflow). The two DABs jobs were also renamed to describe their scenario (*Fleet Pipeline — Simulated IoT Sensors (mock data)* / *Fleet Pipeline — Real Vehicle Telemetry (VED replay)*).
- **Push alerting to Slack + PagerDuty** (`src/fleet_alerting/`, ADR-009): CRITICAL/DANGER (and, per config, WARNING/OVERSPEED) alerts are pushed **from the Gold run** — event-driven, not via Grafana polling — to Slack (team awareness) and PagerDuty (on-call escalation). Severity-routed and deduplicated per driver. The outgoing message is built from an allowlist of operational/derived fields, so **special-category biometrics never leave the platform** (a test asserts the allowlist is disjoint from the governed special-category columns). Delivery is best-effort (records `alerts_dispatch_errors` on `pipeline_metrics`, never fails the run), uses only stdlib `urllib` (no new dependency), and is a documented no-op until a Slack webhook / PagerDuty routing key is configured (via DABs variables → a secret scope in production). The generated Art. 30 record now names Slack/PagerDuty as recipients and states biometrics are never sent externally.
- **Real-world data replay** (`src/replay/`, ADR-008): parses Vehicle Energy Dataset trips (committed real sample: 10 vehicles / 18 trips, Apache-2.0, `data/ved/`), pseudonymises them onto the fleet roster, rebases them onto a replay anchor, and emits both streams in the mock producers' exact schemas. Driver biometrics are simulated **conditioned on the real driving events** (hard braking detected in the raw trace, overspeed from `RISK_MODEL`), deterministic per seed. `scripts/fetch_ved.py` pulls the full dataset.
- **`real_telemetry_job`** in the DABs bundle: the identical 8-task medallion DAG fed by real data (downstream tasks are YAML aliases of the monitoring job's), with a 30-minute periodic trigger — PAUSED by default (`var.replay_pause_status`) — for continuous operation.
- **Masking coverage completed** (ADR-007 updated): UC column masks now also cover `fleet_live_status_quarantine` (DQ-failing rows are still raw Art. 9 biometrics) and the `driver_safety_metrics` aggregates (`avg_heart_rate` / `avg_stress` — per-driver aggregation does not de-identify), via a classified aggregate contract (`METRICS_COLUMN_CLASSES`) and typed mask-UDF variants (INT sources / DOUBLE aggregates). The generated Art. 30 record documents the aggregate table.
- Sensor **null-rate observability**: the Gold notebook now records `heart_rate`/`stress_score`/`speed` null rates in `pipeline_metrics` (wearable dropout shows on the dashboard instead of silently degrading the score).
- 18 new tests (138 total): replay parsing against the real sample, harsh-brake detection, biometric determinism/decay, tick-grid alignment, a real-data end-to-end (replayed trips → production Silver → non-empty Gold enriched view), aggregate/quarantine masking, and the aggregate classification contract.

### Changed
- **`DATABRICKS_HOST` is no longer a stored secret** — the deploy workflow derives the workspace URL from the `01_infra` `workspace_url` Terraform output and passes it to the bundle-deploy job as a job output; the run workflow lets `bundle.sh` fetch it from Terraform (it already sets up AWS OIDC + Terraform). This removes the one manual copy-paste-after-apply step, so a full deploy needs no post-apply human action.
- Renamed the Terraform remote-state S3 bucket `generic-terraform-state-eu-central-1` → `fleet-risk-lakehouse-tfstate-eu-central-1` (project-specific, less likely to collide in the global S3 namespace) across all three layers' backend blocks, the two `terraform_remote_state` data sources, ADR-001, and CLAUDE.md.
- `live_status_select_sql` now enumerates the classified Gold contract columns instead of Databricks-only `SELECT * EXCEPT(rn)` — the exact production SQL runs verbatim on OSS Spark (test hack removed).
- `setup.sh` creates the **test** environment (`.venv` ← `requirements-dev.txt`); the conflicting Databricks Connect env is opt-in (`--connect` → `.venv-connect`) — following the documented setup then `make test` now works.
- `terraform.sh` loads `.env` via `set -a; source` (handles quotes/spaces/comments); `bundle.sh` is target-aware (`BUNDLE_TARGET`, `BUNDLE_JOB_NAME`); S3 backends use `use_lockfile = true` (state locking); `databricks/setup-cli` pinned to a commit SHA; `requirements.txt` fully pinned (dead `databricks-cli`/`black` deps removed); bronze/silver notebooks reuse an existing `spark` session instead of always building a Connect session.

### Fixed
- **Layer 03 catalog/volume "inconsistent final plan"** (`databricks_unity_catalog`): Databricks normalises an external-location URL by stripping the trailing slash, so `databricks_external_location.this[*].url` differs between plan (`…/unity-catalog/`) and apply (`…/unity-catalog`) — which the provider rejects when the catalog `storage_root` and external-volume `storage_location` reference it. Wrapped both references in `trimsuffix(…, "/")` so the computed path is identical at plan and apply.
- **Layer 03 apply race** (`databricks_unity_catalog`): the external-location grants and catalog grants referenced their securables by name (string), so Terraform never ordered them after the location/catalog creation — they raced ahead and failed with `External Location/Catalog 'X' does not exist` (cascading a spurious storage-credential read error) on a fresh apply. Added the missing `depends_on = [databricks_external_location.this]` / `[databricks_catalog.this]`, matching the schema/volume grants that already had it.
- Doc drift: task counts (7 → 8), `app/README.md` example schema (`gold` → `operations`), test counts, and the repo maps in `README.md`/`CLAUDE.md`.
- `CLAUDE.md` engineering reference: environment variables, Terraform layer apply/destroy order, DABs commands, Grafana setup, and known gotchas.
- Architecture Decision Records under `docs/adr/`:
  - ADR-001 — 3-layer Terraform with isolated remote state.
  - ADR-002 — 60-second temporal join window for tracker/watch correlation.
  - ADR-003 — Databricks SQL Warehouse as the Grafana query backend.
- `terraform-plan-pr.yml` workflow: runs `terraform plan` for all three layers on pull requests and posts sticky per-layer comments, with a fork guard.
- `.pre-commit-config.yaml` with `terraform_fmt`, `terraform_validate`, `black`, and `ruff` hooks.
- Derived numeric `risk_score` column in the Gold layer, propagated to `fleet_live_status`, `fleet_safety_alerts`, and aggregated (`avg_risk_score` / `max_risk_score`) in `driver_safety_metrics`.
- Inline data-quality assertions in the Gold notebook: non-empty enriched view, NULL key checks, `risk_score` range validation, and row-count guards.
- Repository polish: README badges, table of contents, and "What This Project Demonstrates" section; `CHANGELOG.md`; GitHub issue and pull request templates; Dependabot configuration.
- Module-level and function-level docstrings plus type hints on the mock-generator producer scripts.
- gitleaks secret scanning: a pre-commit hook plus a CI workflow (`gitleaks.yml`, full git history); hardened `.gitignore` (secrets baseline).

### Changed
- `requirements.txt` now includes `pre-commit`.
- Renamed the project to **Fleet Risk Lakehouse** (previously "Real-Time IoT Fleet Analytics"; repo `databricks-fleet-dabs-orchestration`).
- `deploy-fleet-pipeline.yml` is now **manual-only** (`workflow_dispatch`); removed the automatic `push: main` trigger so a code/doc merge can never deploy live infrastructure.

## [0.1.0] - 2026-05-31

Initial public baseline of the Fleet Risk Lakehouse platform.

### Added
- Medallion data pipeline on Databricks: Bronze (Auto Loader ingestion of CSV trackers and JSON watches), Silver (type casting, deduplication, outlier filtering), and Gold (temporal join, safety metrics, alerts).
- Python IoT mock generators (`producer_trackers.py`, `producer_watches.py`) with intentional error/noise injection for resilience testing.
- Three-layer Terraform infrastructure: AWS foundation (S3, IAM, Secrets Manager), Databricks account/workspace, and Unity Catalog governance, with reusable modules.
- `terraform.sh` multi-layer orchestrator with automatic SPN secret injection from AWS Secrets Manager.
- Databricks Asset Bundle (`databricks.yml`) defining the 7-task fleet monitoring job DAG, plus `bundle.sh` deployment wrapper.
- `setup.sh` local environment bootstrapper and `.env.example` template.
- GitHub Actions `deploy-fleet-pipeline.yml`: full Terraform apply and DABs deploy on push to `main`.
- MIT License.

[Unreleased]: https://github.com/theofanis-tsakanikas/fleet-risk-lakehouse/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/theofanis-tsakanikas/fleet-risk-lakehouse/releases/tag/v0.1.0
