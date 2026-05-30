# CLAUDE.md — Fleet Monitoring Platform: Engineering Reference

## Quick Start

```bash
# 1. Bootstrap local environment (creates .venv, installs deps, copies .env template)
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

## Repo Map

```
.
├── .github/workflows/
│   ├── deploy-fleet-pipeline.yml     # Trigger: push to main — full apply + DABs deploy
│   └── terraform-plan-pr.yml         # Trigger: pull_request — plan all 3 layers, post sticky comments
├── notebooks/
│   ├── bronze/                        # Auto Loader ingestion (cloudFiles, CSV/JSON → Delta)
│   │   ├── bronze_trackers.py
│   │   └── bronze_watches.py
│   ├── silver/                        # Type casting, deduplication, outlier filtering
│   │   ├── silver_trackers.py
│   │   └── silver_watches.py
│   └── gold/                          # Temporal join, risk scoring, 3 business Gold tables
│       └── gold_fleet_monitoring_enrichment.py
├── src/mock_generator/                # Python IoT simulators (CSV trackers, JSON watches)
│   ├── fleet_config.json              # 10 driver / truck / watch device mappings
│   ├── producer_trackers.py
│   └── producer_watches.py
├── terraform/
│   ├── 01_infra/                      # AWS: S3, IAM, Secrets Manager, SPN, Metastore, Workspace
│   ├── 02_workspace/                  # Databricks: SQL Warehouse, metastore-level grants
│   ├── 03_unity_catalog/              # UC: storage credentials, external locations, catalogs, schemas, volumes
│   └── modules/                       # Reusable modules consumed by the 3 layers above
│       ├── aws_foundation/            # S3 buckets + Secrets Manager
│       ├── aws_iam/                   # IAM roles for data lake and metastore
│       ├── databricks_account/        # SPN, admin group, metastore
│       ├── databricks_workspace/      # Workspace resource + NCC
│       ├── databricks_workspace_config/  # SQL Warehouse + grants
│       └── databricks_unity_catalog/  # Storage credentials, external locations, catalogs, schemas, volumes
├── databricks.yml                     # DABs bundle definition: 7-task job, variables, sync rules
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
| `AWS_ACCESS_KEY_ID` | All Terraform layers, mock generators | AWS IAM admin user access key |
| `AWS_SECRET_ACCESS_KEY` | All Terraform layers, mock generators | AWS IAM admin user secret |
| `AWS_DEFAULT_REGION` | All | Hardcode to `eu-central-1` |
| `TF_VAR_databricks_account_id` | `01_infra` | Databricks Account Console (top-right menu) |
| `TF_VAR_databricks_client_id` | `01_infra` | Pre-existing **Account Admin** SPN client ID |
| `TF_VAR_databricks_client_secret` | `01_infra` | Pre-existing Account Admin SPN secret |
| `DATABRICKS_CLIENT_ID` | `bundle.sh` (local dev) | Same value as `TF_VAR_databricks_client_id` |
| `DATABRICKS_CLIENT_SECRET` | `bundle.sh` (local dev) | Same value as `TF_VAR_databricks_client_secret` |
| `DATABRICKS_HOST` | `bundle.sh`, notebooks | `workspace_url` output from `01_infra`; set automatically in CI |
| `DATA_LAKE_BUCKET` | Mock generators | S3 bucket name (`dbx-data-lake-bucket`) |
| `S3_FOLDER_WATCHES` / `S3_FOLDER_TRACKERS` | Mock generators | Landing zone S3 paths |
| `WATCHES_CATALOG` / `TRACKERS_CATALOG` / `GOLD_CATALOG` | Notebooks | Unity Catalog catalog names |
| `*_SCHEMA` / `*_TABLE` / `*_VOLUME` variables | Notebooks | UC object names; defaults match `databricks.yml` |

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
./bundle.sh run        # Trigger fleet_monitoring_job immediately and tail output
```

`bundle.sh` resolves `DATABRICKS_HOST` and `SPN_ID` at runtime:
- **CI/CD path:** These are injected as environment variables by the GitHub Actions workflow.
- **Local path:** The script calls `./terraform.sh 01_infra output -raw` to read them from Terraform state.

The bundle deploys to the `dev` target defined in `databricks.yml`. The job DAG runs 7 tasks:

```
generate_mock_trackers ──► bronze_trackers ──► silver_trackers ──┐
                                                                   ├──► gold_fleet_enrichment
generate_mock_watches  ──► bronze_watches  ──► silver_watches  ──┘
```

Bronze and Silver for each stream run in parallel. Gold waits for both Silver tasks to complete.

### DABs Variables

`databricks.yml` defines variables with defaults that match the Unity Catalog objects created by
layer `03_unity_catalog`. Override them per-target by editing the `targets` section or via
`--var key=value` flags. The CI/CD pipeline injects `spn_id` at deploy time.

---

## Grafana Setup

Grafana does **not** run locally as a separate process. It connects to the **Databricks SQL
Warehouse** provisioned by layer `02_workspace` (`serverless_bi-dev`, a serverless PRO warehouse).

**Connecting Grafana to the warehouse:**
1. Install the [Grafana Databricks data source plugin](https://grafana.com/grafana/plugins/grafana-databricks-datasource/).
2. In Databricks UI: SQL Warehouses → `serverless_bi-dev` → **Connection Details** → copy the HTTP Path.
3. Configure the data source: Host = `DATABRICKS_HOST`, HTTP Path from step 2, auth = SPN OAuth
   (client ID + secret from `.env`) or a Personal Access Token.
4. Default catalog: `fleet_dev`, schema: `operations`.

The warehouse auto-stops after 10 minutes of inactivity. The first Grafana query after an idle
period will incur a ~20–30 second cold start while the warehouse resumes.

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
