# CLAUDE.md — Fleet Risk Lakehouse: Engineering Reference

## Quick Start

```bash
# 1. Bootstrap local environment (creates the .venv TEST env from requirements-dev.txt
#    + copies the .env template). Add --connect for a separate .venv-connect with
#    databricks-connect — the two must never share an env (connect conflicts with pyspark).
./setup.sh

# 2. Fill in credentials
cp .env.example .env   # then edit .env — see Environment Variables table below

# 3. Deploy infrastructure in mandatory order (see Terraform Layers)
./terraform.sh 01_infra apply
./terraform.sh 02_workspace apply
./terraform.sh 03_unity_catalog apply

# 4. Deploy and run the data pipeline
./bundle.sh deploy
./bundle.sh run
```

---

## Prerequisites (one-time bootstrap)

These must exist **before** the Quick Start — Terraform does not bootstrap them:

**Accounts**
- An **AWS account** and a **Databricks-on-AWS account** with a pre-existing **Account-Admin
  Service Principal** (client id + secret) — the bootstrap identity Terraform authenticates as.

**AWS bootstrap (manual)**
- The **Terraform state bucket** `fleet-risk-lakehouse-tfstate-eu-central-1` (region `eu-central-1`,
  encryption on) — `terraform init` fails without it.
- **Local runs:** an IAM admin user with access keys (in `.env`). **CI:** a **GitHub OIDC
  provider** + an IAM role (the `AWS_DEPLOY_ROLE_ARN` secret) trusted by this repo, with
  permissions over S3 / IAM / Secrets Manager and the state bucket.

**Databricks account (manual)**
- An account-level group **`fleet_safety_officers`** (the `mask_privileged_group`), created
  **before the deploy** — layer 01 looks it up (data source) and adds the **project SPN** to it
  automatically (so the pipeline's own biometric null-rate metrics read unmasked; a missing group
  fails the apply). You add the **human** members: yourself, plus the dashboard's query principal
  if you want Grafana/Streamlit to show raw biometrics. Its members are the only principals that
  see unmasked biometrics / precise location — everyone else sees masked (see
  [ADR-007](docs/adr/ADR-007-column-masking.md) / Gotcha #8).

**Credentials**
- **Local:** `cp .env.example .env`, then fill the AWS keys, `TF_VAR_aws_account_id` (your real
  12-digit id), and the Account-Admin SPN (`TF_VAR_databricks_*` / `DATABRICKS_*`). The **project**
  SPN (`TF_VAR_spn_*`) is injected automatically by `terraform.sh` — never set by hand.
- **CI** (repo → Settings → Secrets and variables → Actions):
  - Secrets: `AWS_DEPLOY_ROLE_ARN`, `AWS_ACCOUNT_ID`, `DATABRICKS_ACCOUNT_ID`,
    `DATABRICKS_ADMIN_CLIENT_ID`, `DATABRICKS_ADMIN_CLIENT_SECRET`. (`DATABRICKS_HOST` is **not**
    stored — the workflows derive the workspace URL from the `01_infra` Terraform output and pass
    it between jobs, so there is no host to copy-paste after an apply.)
  - Variables: `AWS_DEFAULT_REGION` (e.g. `eu-central-1`).

**Optional (feature-gated — a no-op if omitted)**
- **Alerting:** a Slack Incoming Webhook URL + a PagerDuty Events API v2 routing key, wired to the
  DABs vars `slack_webhook_url` / `pagerduty_routing_key` (via a Databricks secret scope) — see
  [ADR-009](docs/adr/ADR-009-alert-notifications.md).
- **Grafana:** a Grafana instance with the Databricks datasource plugin pointed at the
  `serverless_bi-dev` SQL Warehouse (catalog `fleet_dev`, schema `operations`).

---

## Make targets (the front door)

A [Makefile](Makefile) wraps the tooling in one discoverable interface — run `make help` to
list everything. It does **not** replace the shell scripts: the heavy logic (multi-layer
Terraform ordering, SPN secret injection, DABs host/SPN resolution) stays in
`terraform.sh` / `bundle.sh` / `setup.sh`, which the GitHub workflows also call; `make`
just gives them a uniform front door and bundles the quality gates.

```bash
make help                       # list all targets
make setup                      # ./setup.sh  (venv + .env)
make check                      # run every gate the CI runs: lint + fmt-check + test + govern-check
make test | lint | fmt | govern-docs
make plan LAYER=01_infra        # ./terraform.sh 01_infra plan   (also apply/destroy/output/tf-fmt)
make infra-up                   # apply all 3 layers in the mandatory order (01 → 02 → 03)
make infra-down                 # destroy in reverse order (03 → 02 → 01)
make deploy | run | validate    # ./bundle.sh <action>
```

The four CI gate steps in [ci.yml](.github/workflows/ci.yml) call `make lint|fmt-check|test|
govern-check` (with `PYTHON=python`), so the gate commands are defined in exactly one place
and `make check` reproduces CI locally. The Makefile defaults `PYTHON` to `.venv/bin/python`
(its `python` symlink works even though the venv's `pip` shebang is stale — use
`$(PYTHON) -m pip`).

---

## Repo Map

```
.
├── .github/workflows/
│   ├── ci.yml                        # Trigger: PR + push main — lint + fmt-check + test + govern-check gates
│   ├── deploy-fleet-pipeline.yml     # Trigger: manual (workflow_dispatch) — full apply + DABs deploy
│   ├── run-fleet-pipeline.yml        # Trigger: manual (workflow_dispatch) — pick a scenario (mock/real) & run it
│   ├── destroy-infrastructure.yml    # Trigger: manual (workflow_dispatch) — teardown 03→02→01 (cumulative scope + confirm)
│   ├── terraform-plan-pr.yml         # Trigger: pull_request — plan all 3 layers, post sticky comments
│   └── gitleaks.yml                  # Trigger: PR + push — secret scan over full git history
├── notebooks/
│   ├── bronze/                        # Auto Loader ingestion (cloudFiles, CSV/JSON → Delta)
│   │   ├── bronze_trackers.py
│   │   └── bronze_watches.py
│   ├── silver/                        # Type casting, deduplication, outlier filtering
│   │   ├── silver_trackers.py
│   │   └── silver_watches.py
│   └── gold/                          # Temporal join, risk scoring, 3 business Gold tables + SCD2 dim
│       ├── gold_fleet_monitoring_enrichment.py  # Enrich + DQ suite + masking + drift + metrics
│       └── gold_dim_driver.py         # SCD Type 2 driver→truck assignment dimension
├── src/fleet_transforms/              # Pure, unit-tested transform logic (no Spark session / I/O)
│   ├── silver.py                      # Silver cleansing rules (trackers + watches)
│   ├── gold.py                        # Gold SQL builders (temporal join, risk, explainability) + DQ suite
│   ├── risk_model.py                  # RISK_MODEL — single source of truth for the score + its explanation
│   ├── quality.py                     # Declarative DQ framework (Expectation/Severity, evaluate/split/enforce)
│   ├── observability.py               # pipeline_metrics builders (row counts, join match rate, null rates)
│   ├── dimensions.py                  # SCD2 reference (apply_scd2) + Delta MERGE builder
│   └── drift.py                       # Risk-score distribution drift (PSI over risk bands)
├── src/fleet_governance/              # Offline governance: column classification + generated docs
│   ├── classification.py              # Gold column classification (biometrics = GDPR Art. 9 special category)
│   ├── masking.py                     # Enforced UC column masks (biometrics + location), derived from classification
│   └── generate.py                    # Generates docs/governance/ (risk model card + GDPR Art. 30 record)
├── src/fleet_alerting/                # Push safety alerts (Slack + PagerDuty) from the pipeline — ADR-009
│   ├── alerts.py                      # Pure: severity routing + Slack/PagerDuty payloads (no Art. 9 data)
│   └── dispatch.py                    # Config + delivery adapters (urllib, dry-run, best-effort)
├── src/mock_generator/                # Python IoT simulators (CSV trackers, JSON watches)
│   ├── fleet_config.json              # 10 driver / truck / watch device mappings
│   ├── generators.py                  # Pure, unit-tested event generators (dirty-data injection logic)
│   ├── producer_trackers.py
│   └── producer_watches.py
├── src/replay/                        # Real-data replay (VED trips → the same Bronze contract)
│   ├── ved.py                         # VED CSV parsing + trip normalisation/resampling
│   ├── biometrics.py                  # Biometrics conditioned on real hard-braking/overspeed events
│   ├── replay.py                      # Driver assignment, timeline rebasing, event emission
│   └── producer_replay.py             # CLI/job entry point (batch files → Volume/S3)
├── data/ved/                          # Committed REAL sample (10 vehicles, 18 trips) + attribution README
├── scripts/fetch_ved.py               # Pull the full VED dataset into data/ved/full/ (gitignored)
├── docs/governance/                   # Generated: RISK_MODEL_CARD.md + DATA_PROCESSING_RECORD.md (CI --check)
├── docs/adr/                          # ADR-001..009 (layered state, join window, BI, micro-batch, DQ, SCD2, masking, replay, alerting)
├── docs/architecture.md               # Mermaid diagrams (data flow, Gold gates, Terraform layers)
├── docs/RUNBOOK.md                    # Ops: latency/cost, observability, incidents, recovery
├── docs/SCALING.md                    # What changes (and doesn't) from 10 → 10,000 drivers
├── docs/TESTING.md                    # Testing philosophy + coverage map (infra-free suite)
├── app/                               # Streamlit "Fleet Safety Command Center" over the Gold layer
│   ├── streamlit_app.py               # UI: KPIs, risk map, leaderboard, driver drill-down, Medallion view
│   ├── fleet_data.py                  # Data layer: offline demo synthesis + Databricks SQL (live) reader
│   └── requirements.txt               # UI deps (light; no Spark)
├── terraform/
│   ├── 01_infra/                      # AWS: S3, IAM, Secrets Manager, SPN, Metastore, Workspace
│   ├── 02_workspace/                  # Databricks: SQL Warehouse, metastore-level grants
│   ├── 03_unity_catalog/              # UC: storage credentials, external locations, catalogs, schemas, volumes
│   ├── 04_grafana/                    # Amazon Managed Grafana workspace + service-account token + Infinity plugin install (standalone)
│   ├── 05_grafana_content/            # Grafana datasource (Databricks-over-Infinity) + pipeline-observability dashboard, as code
│   └── modules/                       # Reusable modules consumed by the layers above
│       ├── aws_foundation/            # S3 buckets + Secrets Manager
│       ├── aws_iam/                   # IAM roles for data lake and metastore
│       ├── aws_grafana/               # Amazon Managed Grafana workspace + IAM role + SSO admin association
│       ├── databricks_account/        # SPN, admin group, metastore
│       ├── databricks_workspace/      # Workspace resource + NCC
│       ├── databricks_workspace_config/  # SQL Warehouse + grants
│       └── databricks_unity_catalog/  # Storage credentials, external locations, catalogs, schemas, volumes
├── databricks.yml                     # DABs bundle: 2 jobs × 8 tasks (mock + real-data replay), variables, sync
├── Makefile                           # Front door: `make help` — wraps the 3 scripts + bundles the CI gates
├── terraform.sh                       # Multi-layer Terraform orchestrator with automatic secret injection
├── bundle.sh                          # DABs wrapper: resolves host/SPN from Terraform or env vars
└── setup.sh                           # One-time local dev bootstrapper (venv + .env creation)
```

**Notebooks are plain `.py` files** with Databricks magic comment markers (`# COMMAND ----------`). They run identically as Databricks Job tasks or locally via Databricks Connect.

---

## Environment Variables

All variables live in `.env` (gitignored). Seed it from the template:

```bash
cp .env.example .env
```

| Variable | Used By | Source |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | Local Terraform runs, mock generators | AWS IAM admin user access key (local only — CI authenticates via OIDC) |
| `AWS_SECRET_ACCESS_KEY` | Local Terraform runs, mock generators | AWS IAM admin user secret (local only — CI authenticates via OIDC) |
| `AWS_DEFAULT_REGION` | All | Hardcode to `eu-central-1` |
| `TF_VAR_aws_account_id` | `01_infra` (IAM trust policies) | Your real 12-digit AWS account ID (local only — CI reads the `AWS_ACCOUNT_ID` secret). The committed `.tf` default is a placeholder. |
| `TF_VAR_databricks_account_id` | `01_infra` | Databricks Account Console (top-right menu) |
| `TF_VAR_databricks_client_id` | `01_infra` | Pre-existing **Account Admin** SPN client ID |
| `TF_VAR_databricks_client_secret` | `01_infra` | Pre-existing Account Admin SPN secret |
| `DATABRICKS_CLIENT_ID` | `bundle.sh` (local dev) | Same value as `TF_VAR_databricks_client_id` |
| `DATABRICKS_CLIENT_SECRET` | `bundle.sh` (local dev) | Same value as `TF_VAR_databricks_client_secret` |
| `DATABRICKS_HOST` | `bundle.sh`, notebooks | Derived from the `workspace_url` output of `01_infra` — **never a stored secret**. In CI the deploy job passes it to the bundle job as an output; `bundle.sh` otherwise fetches it from Terraform. Set it by hand only for a standalone local run. |
| `DATA_LAKE_BUCKET` | Mock generators | S3 bucket name (`fleet-risk-lakehouse-datalake-eu-central-1`) |
| `S3_FOLDER_WATCHES` / `S3_FOLDER_TRACKERS` | Mock generators | Landing zone S3 paths |
| `WATCHES_CATALOG` / `TRACKERS_CATALOG` / `GOLD_CATALOG` | Notebooks | Unity Catalog catalog names |
| `*_SCHEMA` / `*_TABLE` / `*_VOLUME` variables | Notebooks | UC object names; defaults match `databricks.yml` |

> **CI authentication is OIDC-based:** both GitHub workflows assume the IAM role in the
> `AWS_DEPLOY_ROLE_ARN` repository secret via `aws-actions/configure-aws-credentials` —
> no long-lived AWS keys are stored in GitHub. The role's trust policy must allow the
> repository's GitHub OIDC provider. The deploy workflow is **manual-only**
> (`workflow_dispatch`) — it is never triggered on push, so a merge to `main` cannot
> deploy infrastructure. (A required-reviewer gate on the `production` environment would
> be the stronger control, but it requires GitHub Pro+ on private repos.)

> **`TF_VAR_spn_client_id` and `TF_VAR_spn_client_secret` are never set manually.**
> `terraform.sh` fetches them automatically from AWS Secrets Manager after layer `01_infra` has been applied — see [Terraform Secret Injection](#terraform-secret-injection) below.

---

## Terraform Layers

### Mandatory Apply Order

```bash
./terraform.sh 01_infra apply        # ~8–12 min: S3, IAM, SPN, Databricks Metastore + Workspace
./terraform.sh 02_workspace apply    # ~3–5 min:  SQL Warehouse, metastore-level grants
./terraform.sh 03_unity_catalog apply # ~3–5 min: storage credentials, catalogs, schemas, volumes
```

**Why this order is mandatory:** Layers `02_workspace` and `03_unity_catalog` both use
`data "terraform_remote_state" "infra"` to read outputs from layer `01_infra`'s S3 state file:
`workspace_url`, `metastore_id`, `datalake_role_arn`, `secrets_manager_id`.
If `01_infra` has not been applied, those reads return errors and `init` or `plan` will fail for layers 02 and 03.

### Mandatory Destroy Order (reverse)

```bash
./terraform.sh 03_unity_catalog destroy   # Remove UC objects while workspace still exists
./terraform.sh 02_workspace destroy       # Remove SQL Warehouse while AWS IAM still valid
./terraform.sh 01_infra destroy           # Remove S3, IAM, SPN, Workspace
```

Destroying `01_infra` before `03_unity_catalog` would orphan Unity Catalog resources whose
backing S3 external location no longer exists; Terraform cannot clean them up cleanly without an
accessible workspace.

### Remote State Architecture

Each layer has its own isolated S3 backend key — all in the same bucket with encryption enabled:

| Layer | State S3 key |
|---|---|
| `01_infra` | `dev/01-infra/terraform.tfstate` |
| `02_workspace` | `dev/02-workspace/terraform.tfstate` |
| `03_unity_catalog` | `dev/03-unity-catalog/terraform.tfstate` |

State isolation means a failed or partial destroy of layer `03` cannot corrupt layer `01`'s state,
and concurrent plans on different layers do not create lock contention between each other.

### Terraform Secret Injection

For layers `02_workspace` and `03_unity_catalog`, `terraform.sh` automatically:

1. Calls `terraform -chdir=terraform/01_infra output -raw secrets_manager_id` to read the
   AWS Secrets Manager ARN stored in layer 01's state.
2. Calls `aws secretsmanager get-secret-value` to retrieve the JSON payload written there during
   layer `01_infra` apply (which creates the project SPN and stores its credentials).
3. Exports `TF_VAR_spn_client_id` and `TF_VAR_spn_client_secret` into the shell — Terraform
   picks them up via the `TF_VAR_` prefix convention.

This happens for `plan`, `apply`, and `destroy` actions on layers 02 and 03.

**Gotcha:** If you run layer 02 or 03 before layer 01 has been applied at least once, the
`secrets_manager_id` output is empty. `terraform.sh` will warn but continue with empty strings,
causing an authentication failure at Terraform's provider initialization — not a clear dependency error.

### `terraform.sh` Command Reference

```bash
./terraform.sh <layer> fmt          # Run terraform fmt -recursive in the layer directory
./terraform.sh <layer> init         # Initialize backend and download providers
./terraform.sh <layer> plan         # Init + plan (secret injection for layers 02/03)
./terraform.sh <layer> apply        # Init + apply -auto-approve (secret injection for 02/03)
./terraform.sh <layer> destroy      # Init + destroy -auto-approve (secret injection for 02/03)
./terraform.sh <layer> output       # Show all outputs for the layer
./terraform.sh <layer> output -raw workspace_url   # Get a single output value
```

---

## DABs Commands

```bash
./bundle.sh validate   # Validate databricks.yml against the workspace (no-op check)
./bundle.sh deploy     # Upload notebooks/src to workspace, register the job definition
./bundle.sh run        # Trigger simulated_sensors_job immediately and tail output
./bundle.sh destroy    # Remove the deployed jobs + uploaded files from the workspace
```

`bundle.sh` resolves `DATABRICKS_HOST` and `SPN_ID` at runtime:
- **CI/CD path:** These are injected as environment variables by the GitHub Actions workflow.
- **Local path:** The script calls `./terraform.sh 01_infra output -raw` to read them from Terraform state.

The bundle deploys to the `dev` target defined in `databricks.yml` (override with
`BUNDLE_TARGET=prod`). It defines **two jobs** with the identical 8-task medallion DAG:

```
generate_mock_trackers ──► bronze_trackers ──► silver_trackers ──┬──► gold_fleet_enrichment
                                                                  └──► build_dim_driver
generate_mock_watches  ──► bronze_watches  ──► silver_watches  ──────► gold_fleet_enrichment
```

- `simulated_sensors_job` — mock generators (dirty-data injection); display name
  *"Fleet Pipeline — Simulated IoT Sensors (mock data)"*, manual trigger.
- `real_telemetry_job` — `replay_trackers` / `replay_watches` stream **real VED trips**
  (see [ADR-008](docs/adr/ADR-008-real-data-replay.md)); display name *"Fleet Pipeline —
  Real Vehicle Telemetry (VED replay)"*. Both tasks get the same
  `{{job.start_time.iso_datetime}}` anchor so the streams align inside the ±60s join
  window. It carries a 30-minute periodic trigger, **PAUSED by default**
  (`var.replay_pause_status: UNPAUSED` enables continuous operation). Run it manually
  with `BUNDLE_JOB_NAME=real_telemetry_job ./bundle.sh run`.

> **Pick a scenario from GitHub with one click.** The **Run Fleet Pipeline**
> workflow ([run-fleet-pipeline.yml](.github/workflows/run-fleet-pipeline.yml)) exposes a
> `workflow_dispatch` **choice** input — *"Simulated IoT sensors (mock data)"* vs *"Real
> vehicle telemetry (VED replay)"* — maps it to the matching bundle job, deploys the current
> bundle, and runs it. No infrastructure re-apply (that stays in the deploy workflow).

Bronze and Silver for each stream run in parallel. `gold_fleet_enrichment` waits for both
Silver tasks; `build_dim_driver` (the SCD2 driver dimension) depends only on `silver_trackers`
and runs in parallel with Gold enrichment. The downstream tasks of the two jobs are YAML
aliases of the same definitions — they cannot drift apart.

### DABs Variables

`databricks.yml` defines variables with defaults that match the Unity Catalog objects created by
layer `03_unity_catalog`. Override them per-target by editing the `targets` section or via
`--var key=value` flags. The CI/CD pipeline injects `spn_id` at deploy time.

---

## Grafana Setup

Grafana does **not** run locally. It is **Amazon Managed Grafana** (layer `04_grafana`), and the
datasource + dashboards are **provisioned as code** (layer `05_grafana_content`) — there is **no
manual UI setup**. `terraform apply` on those two layers reproduces the whole thing. See
[ADR-010](docs/adr/ADR-010-grafana-infinity-datasource.md).

**How it connects (no Enterprise plugin):** the official Grafana Databricks plugin is Enterprise-only
(+$45/active user/mo on AMG), so instead the dashboards query through the **free OSS
[Infinity](https://grafana.com/grafana/plugins/yesoreyeram-infinity-datasource/) datasource**, which
POSTs SQL to the Databricks **SQL Statement Execution REST API** (`/api/2.0/sql/statements`) against
the `serverless_bi-dev` warehouse (layer `02_workspace`). Auth is **OAuth2 machine-to-machine** with
the read-only BI SPN (`grafana-bi-reader-dev`): client id = the `01_infra` output
`bi_reader_application_id`, secret = AWS Secrets Manager key `bi_reader_client_secret`, token URL
`…/oidc/v1/token`, scope `all-apis`. That SPN is **not** an account admin — a `data_analysts` member
with `SELECT` on `fleet_dev.operations` **and** `fleet_dev.metadata` (the `pipeline_metrics` fact),
and **not** in `fleet_safety_officers` — so Grafana sees risk scores / drift / counts / coarse
location but **raw biometrics stay masked** (to show them, add the SPN to `fleet_safety_officers`).

**Deploy / tear down (standalone from the 01→02→03 stack):**

```bash
export TF_VAR_grafana_admin_user_id=<your IAM Identity Center user id>  # ADMIN login grant
./terraform.sh 04_grafana apply          # workspace + service-account token + Infinity plugin install
./terraform.sh 05_grafana_content apply  # Infinity datasource + the pipeline-observability dashboard
# ... or `make grafana-up`  /  `make grafana-down` (reverse order). 04+05 need 01/02/03 already applied.
```

Layer 05 authenticates the `grafana` provider with the **ADMIN service-account token** layer 04
emits (a 30-day token — re-apply layer 04 to rotate, then layer 05). The Infinity queries use the
**backend** parser (server-side), so they also work for Grafana alerting; the frontend UQL parser
does **not** (browser-only). Login to the workspace is via **IAM Identity Center (SSO)**.

The warehouse auto-stops after 10 minutes of inactivity; the first Grafana query after an idle period
incurs a ~20–30 second cold start while it resumes.

**Running Grafana locally (without Databricks):** Not supported. Grafana requires a live SQL
Warehouse endpoint; there is no embedded or mocked backend.

---

## Gold Layer: Risk Score

The Gold layer computes a numeric `risk_score` (0–100) in `fleet_enriched_view` and propagates it
to all three Gold tables: as a raw value in `fleet_live_status` and `fleet_safety_alerts`, and as
`avg_risk_score` / `max_risk_score` aggregates in `driver_safety_metrics`. Formula:

```sql
ROUND(
    LEAST(100.0,
        (COALESCE(speed, 0)        / 120.0 * 40) +
        (COALESCE(stress_score, 0) / 100.0 * 35) +
        (COALESCE(heart_rate, 0)   / 110.0 * 25)
    ), 2
) AS risk_score
```

Weights: speed 40% (primary physical hazard), stress 35% (cognitive load), heart rate 25%
(secondary biometric correlated with stress). Normalization denominators align with the alert
thresholds used in `fleet_safety_alerts` (speed 120 km/h, stress 100 max, heart rate 110 bpm
danger threshold). See [ADR-002](docs/adr/ADR-002-temporal-join-window.md) and
[ADR-003](docs/adr/ADR-003-sql-warehouse-grafana.md) for context on the Gold layer design.

> **The formula lives in code, not inline SQL.** Weights, denominators, the cap, and the
> alert thresholds are now defined once in `src/fleet_transforms/risk_model.py`
> (`RISK_MODEL`); `gold.py` builds the SQL from it, and the generated risk model card reads
> from the same object — so the documentation can never drift from the formula. Editing a
> weight means running `PYTHONPATH=src python -m fleet_governance.generate` (CI's `--check`
> enforces it).

> **Explainability + biometric governance.** The Gold view now also emits the per-factor
> point contributions (`risk_speed_pts` / `risk_stress_pts` / `risk_heart_rate_pts`) and
> `risk_primary_factor`, so a high-risk driver is explained, not just flagged. Heart rate
> and stress are classified as **special-category data (GDPR Art. 9)** in
> `src/fleet_governance/classification.py`, and a CI test fails if any Gold column is left
> unclassified. See [docs/governance/](docs/governance/README.md) (risk model card + GDPR
> Art. 30 processing record, both generated from the code).

### Gold-layer quality, governance & observability (beyond the joins)

The `gold_fleet_enrichment` task wraps the enrichment with five cross-cutting concerns, each
backed by a pure, unit-tested module under `src/` (the notebook only orchestrates):

- **Declarative data quality** (`quality.py` + `gold.live_status_expectations`): named SQL
  predicates with `ERROR`/`WARN` severities. `fleet_live_status` rows that violate an `ERROR`
  expectation are **quarantined** to `fleet_live_status_quarantine` (annotated with
  `_dq_failures`), not silently dropped; the run fails only if an `ERROR` expectation breached.
  See [ADR-005](docs/adr/ADR-005-declarative-data-quality.md).
- **Enforced column masks** (`fleet_governance/masking.py`): UC column masks on biometrics
  (NULL) and location (coarsened) for everyone outside the `mask_privileged_group`
  (`fleet_safety_officers` by default), derived from the classification — applied to
  **all four** Gold surfaces (live, alerts, quarantine, aggregates; aggregation does not
  de-identify), with typed UDF variants (INT sources vs DOUBLE aggregates). See
  [ADR-007](docs/adr/ADR-007-column-masking.md).
- **Risk-score drift** (`drift.py`): PSI of the risk-score distribution vs. a baseline. Drift
  is a **WARN signal, not a failure** (suspect sensor recalibration before a real safety shift).
- **Pipeline self-metrics** (`observability.py`): a tall, append-only `pipeline_metrics` fact
  (row counts, `join_match_rate`, quarantine count, `risk_score_psi`, band distribution) for
  Grafana. `build_dim_driver` adds SCD2 assignment history — see
  [ADR-006](docs/adr/ADR-006-scd2-driver-dimension.md).
- **Push alerting** (`fleet_alerting/`): CRITICAL/DANGER alerts are pushed from the run to
  Slack + PagerDuty (severity-routed, deduplicated), event-driven rather than via Grafana
  polling. Only allowlisted operational/derived fields are sent — **no Art. 9 biometrics leave
  the platform** — and delivery is best-effort (records `alerts_dispatch_errors`, never fails
  the run). See [ADR-009](docs/adr/ADR-009-alert-notifications.md).

> The risk score is computed once via micro-batch recompute (not continuous streaming) — see
> [ADR-004](docs/adr/ADR-004-micro-batch-execution.md). For ops, see
> [docs/RUNBOOK.md](docs/RUNBOOK.md); for scale, [docs/SCALING.md](docs/SCALING.md); for the
> system shape, [docs/architecture.md](docs/architecture.md).

---

## Known Gotchas

**1. Gold tables are empty after a run**
The Gold notebook uses an `INNER JOIN` with a `±60s` temporal window. If the mock generators
ran with very different timestamps across the two streams (e.g., one stream finished before the
other started), there will be zero matching rows and all three Gold tables will be silently
overwritten as empty. The notebook raises a `ValueError` if `fleet_enriched_view` has 0 rows —
check the job task logs for this message. Verify that both Silver tables contain records with
overlapping `event_timestamp` ranges.

**2. Layer 02/03 plan fails with authentication error on a fresh clone**
Layer `01_infra` must have been applied at least once so the SPN credentials exist in Secrets
Manager. Running `./terraform.sh 02_workspace plan` against a pristine AWS account will fail
with an empty `TF_VAR_spn_client_id`.

**3. `bundle.sh deploy` fails with "Host not found"**
`DATABRICKS_HOST` is not in the environment and the fallback call to
`./terraform.sh 01_infra output -raw workspace_url` returned empty.
Either apply `01_infra` first, or export `DATABRICKS_HOST=https://...` manually.

**4. `terraform plan` references a `backend.tfvars` that does not exist**
`terraform.sh plan` tries `terraform init -backend-config=../../backend.tfvars` first and falls
back to a plain `init` on failure. This fallback works correctly because each layer's
`providers.tf` already contains the full `backend "s3" {}` block inline. The missing file is
harmless; the fallback is intentional.

**5. Pre-commit `terraform_validate` hook requires provider plugins**
The hook runs `terraform validate -backend=false` (no live backend connection needed), but the
Terraform providers must have been downloaded. Run `./terraform.sh <layer> init` once in each
layer directory before running `pre-commit run --all-files` for the first time.

**6. Risk score is capped at 100**
`LEAST(100.0, ...)` caps the composite score. A driver with speed > 120 km/h, stress = 100, and
heart rate > 110 bpm will score exactly 100.0 — not a higher value. NULL sensor readings
contribute 0 to that component via `COALESCE(..., 0)`.

**7. The 60-second temporal join window may produce multiple matches per driver**
For a given watch event, any tracker event within ±60 seconds qualifies. If a driver has two
tracker events within that window (high GPS frequency), the join produces two rows.
`fleet_live_status` resolves this with `ROW_NUMBER() OVER (PARTITION BY driver_id ORDER BY timestamp DESC)`,
keeping only the most recent match per driver. `fleet_safety_alerts` keeps all rows.

**8. Biometrics read as NULL / location looks coarse — usually not a bug**
UC column masks ([ADR-007](docs/adr/ADR-007-column-masking.md)) redact `heart_rate` /
`stress_score` to NULL and coarsen `latitude` / `longitude` for any principal **outside** the
`mask_privileged_group` (`fleet_safety_officers`). If a dashboard shows blanks, check the
querying principal's account-group membership before suspecting the pipeline. The group must
exist at the account level — provision it separately from the workspace Terraform layer.

**9. A run "succeeds" but wrote fewer `fleet_live_status` rows than expected**
Rows that failed an `ERROR` data-quality expectation are diverted to
`fleet_live_status_quarantine` (with a `_dq_failures` column), not written to the live table.
The run only fails if an `ERROR` expectation was breached at all — check
`live_quarantined_rows` in `pipeline_metrics` and inspect the quarantine table. This is by
design ([ADR-005](docs/adr/ADR-005-declarative-data-quality.md)).

**10. `risk_score_psi` is high in `pipeline_metrics`**
Drift is a **WARN signal, not a failure**. A significant PSI (≥ 0.25) most often means a
sensor cohort was recalibrated or a units/config change happened upstream — rule those out via
the `dist_band_*` metrics across recent runs before concluding the fleet actually got riskier.
