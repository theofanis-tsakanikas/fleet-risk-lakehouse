<div style="background-color:#fff8e7; color:#2b2b2b; padding:20px; border-radius:10px;">

# 🚛 Fleet Risk Lakehouse — Real-Time Driver-Risk Analytics on Databricks & AWS
**An Enterprise-Grade Data Platform orchestrated by Terraform & GitHub Actions**

![project_cover_with_title](./images/project_cover_with_title.png)

[![CI](https://github.com/theofanis-tsakanikas/fleet-risk-lakehouse/actions/workflows/deploy-fleet-pipeline.yml/badge.svg)](https://github.com/theofanis-tsakanikas/fleet-risk-lakehouse/actions/workflows/deploy-fleet-pipeline.yml)
[![CI - Local Test Suite](https://github.com/theofanis-tsakanikas/fleet-risk-lakehouse/actions/workflows/ci.yml/badge.svg)](https://github.com/theofanis-tsakanikas/fleet-risk-lakehouse/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Databricks](https://img.shields.io/badge/Databricks-FF3621?logo=databricks&logoColor=white)](https://www.databricks.com/)
[![AWS](https://img.shields.io/badge/AWS-232F3E?logo=amazonwebservices&logoColor=white)](https://aws.amazon.com/)
[![Terraform](https://img.shields.io/badge/Terraform-7B42BC?logo=terraform&logoColor=white)](https://www.terraform.io/)
[![Apache Spark](https://img.shields.io/badge/Apache%20Spark-E25A1C?logo=apachespark&logoColor=white)](https://spark.apache.org/)
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://www.python.org/)

> An end-to-end, Infrastructure-as-Code data lakehouse that correlates vehicle telemetry with driver biometrics to score fleet safety risk in near real time — explainable by design and GDPR-governed.

## 📑 Table of Contents

- [Strategic Overview](#-strategic-overview)
- [What This Project Demonstrates](#-what-this-project-demonstrates)
- [System Architecture & Technical Stack](#️-system-architecture--technical-stack)
- [Project Blueprint](#-project-blueprint)
- [The Medallion Journey (Data Engineering Deep-Dive)](#-the-medallion-journey-data-engineering-deep-dive)
- [Quality, Governance & Observability](#-quality-governance--observability)
- [Executive Observability](#-executive-observability)
- [DevOps & Infrastructure as Code](#️-devops--infrastructure-as-code)
- [Operational Guide (Local Deployment & Lifecycle)](#-operational-guide-local-deployment--lifecycle)
- [Future Roadmap & Scalability](#-future-roadmap--scalability)
- [Conclusion](#-conclusion)

> 📘 For an engineering-focused reference (environment variables, layer apply order, gotchas), see [CLAUDE.md](./CLAUDE.md). For design rationale, see the [Architecture Decision Records](./docs/adr/); for ops, [docs/RUNBOOK.md](./docs/RUNBOOK.md); for scale, [docs/SCALING.md](./docs/SCALING.md); for the system shape, [docs/architecture.md](./docs/architecture.md).

> 🖼️ **Note on screenshots:** the embedded UI captures below are placeholders to be re-recorded against the current pipeline. Each one carries a title and a "what to capture" note. The banner above is final.

## 🎯 Strategic Overview
This project delivers a production-ready **Data Lakehouse** engineered for the high-stakes logistics industry. By correlating **vehicle telemetry** (GPS, speed, fuel) with **driver biometrics** (heart rate, stress), the platform transitions from reactive monitoring to **proactive risk prevention** — producing a per-driver risk score, recomputed per micro-batch run.

The entire ecosystem is governed by **Infrastructure as Code (IaC)**, ensuring that every cloud resource, security policy, and data pipeline is version-controlled, repeatable, and audit-ready.

> ℹ️ **Reference implementation, not a production deployment.** Scope and trade-offs (e.g. micro-batch over continuous streaming) are deliberate and documented in the [ADRs](./docs/adr/).

---

## ✅ What This Project Demonstrates

A portfolio piece showcasing production-grade data and platform engineering practices end to end:

* **Layered Infrastructure as Code** — three isolated Terraform layers (foundation, workspace, governance) with per-layer remote state and automated secret injection. See [ADR-001](./docs/adr/ADR-001-terraform-layered-state.md).
* **Medallion data architecture** — Bronze (Auto Loader ingestion) → Silver (cleansing, deduplication) → Gold (temporal join, risk scoring) on Apache Spark Structured Streaming; the Gold layer is a micro-batch recompute. See [ADR-004](./docs/adr/ADR-004-micro-batch-execution.md).
* **Asynchronous stream correlation** — a ±60-second temporal join window to align independent telemetry and biometric streams. See [ADR-002](./docs/adr/ADR-002-temporal-join-window.md).
* **Real-world data, replayed** — a second job streams **real vehicle telemetry** (the [Vehicle Energy Dataset](data/ved/README.md): genuine GPS traces, speeds, and hard-braking events from Ann Arbor, MI) through the exact same medallion contract, with driver biometrics simulated *conditioned on the real driving events* — honestly documented. A 30-minute periodic trigger (paused by default) runs it continuously. See [ADR-008](./docs/adr/ADR-008-real-data-replay.md).
* **Explainable-by-design risk scoring** — the risk index is a single source of truth in code (`src/fleet_transforms/risk_model.py`); the Gold view emits each factor's point contribution (`risk_speed_pts` / `risk_stress_pts` / `risk_heart_rate_pts`) and `risk_primary_factor`, so a high-risk driver is *explained*, not just flagged. A transparent linear index is a deliberate, auditable choice for a score that escalates a human — documented in the generated [risk model card](docs/governance/RISK_MODEL_CARD.md).
* **Declarative data quality with quarantine** — named SQL expectations (`ERROR`/`WARN`) guard the Gold tables; rows that violate an `ERROR` expectation are *quarantined* to a side table (annotated with `_dq_failures`), not silently dropped. See [ADR-005](./docs/adr/ADR-005-declarative-data-quality.md).
* **Biometric data governance (GDPR), enforced** — heart rate and stress are classified as **special-category data (Art. 9)** in code; a CI test fails if any Gold column is left unclassified, and **Unity Catalog column masks** enforce it (biometrics NULLed, location coarsened) for principals outside the privileged group — on **every** Gold surface carrying the data: the live table, the alerts log, the DQ quarantine side table, and the per-driver aggregates (aggregation does not de-identify). A GDPR Art. 30 processing record + data dictionary are generated from the code. See [ADR-007](./docs/adr/ADR-007-column-masking.md) and [docs/governance/](docs/governance/README.md).
* **Dimensional history (SCD Type 2)** — a `dim_driver` slowly-changing dimension versions each driver→truck assignment over time (Delta `MERGE`). See [ADR-006](./docs/adr/ADR-006-scd2-driver-dimension.md).
* **Pipeline self-observability & drift** — an append-only `pipeline_metrics` fact (row counts, join match rate, quarantine count, risk-score PSI, band distribution) for Grafana, plus risk-score distribution **drift** detection (a WARN signal, not a failure).
* **Push alerting (Slack + PagerDuty)** — CRITICAL/DANGER alerts are pushed **from the pipeline** (not by Grafana polling) to Slack for team awareness and PagerDuty for on-call escalation, severity-routed and deduplicated. Only operational/derived fields are sent — **special-category biometrics never leave the platform**. See [ADR-009](./docs/adr/ADR-009-alert-notifications.md).
* **CI/CD automation** — sticky Terraform `plan` comments on pull requests; a manual (`workflow_dispatch`) full-`apply` deploy that injects live Terraform outputs into the Databricks Asset Bundle; gitleaks secret scanning; and a local test suite (**161 tests**) gating every push.
* **One discoverable interface** — a [`Makefile`](./Makefile) front door (`make help`) wraps the shell scripts and bundles the exact CI gates (`make check`).

---

## 🏗️ System Architecture & Technical Stack
The platform implements a robust **Medallion Architecture**, providing full data lineage and automated quality enforcement.

* **Cloud Infrastructure:** AWS (S3, Secrets Manager, IAM).
* **Storage Strategy:** Isolated triple-bucket architecture (Data, Metadata, Terraform State).
* **Governance:** Databricks Unity Catalog (UC) — fine-grained access control **and enforced column masks** on special-category data.
* **Orchestration:** Databricks Asset Bundles (DABs) — two 8-task Workflow DAGs (mock data on demand; real-data replay on a periodic trigger).
* **Engine:** Apache Spark (Structured Streaming) & Python; pure, unit-tested transform logic under `src/`.
* **CI/CD & Automation:** GitHub Actions, Terraform, Bash, a `Makefile` front door.
* **Observability:** Grafana dashboards and a Streamlit "Fleet Safety Command Center" (`app/`) over a serverless Databricks SQL Warehouse, fed by a `pipeline_metrics` fact. The Streamlit app also runs fully offline in a faithful demo mode (same risk formula, no cloud).
* **Alerting:** pipeline-triggered push notifications to Slack (team awareness) + PagerDuty (on-call escalation) — severity-routed, deduplicated, and biometric-safe (no special-category data leaves the platform). See [ADR-009](./docs/adr/ADR-009-alert-notifications.md).

> 🎥 **[ TO RE-RECORD ]** — *System Architecture diagram*
> The live, code-versioned Mermaid diagrams (data flow, Gold quality/governance gates, Terraform layers) are in **[docs/architecture.md](./docs/architecture.md)** — render those, or capture a polished diagram. (The previous `images/architecture.png` predates the 8-task DAG and the governance/quality additions.)

---

## 📂 Project Blueprint
```text
fleet-risk-lakehouse/
├── .github/workflows/         # CI (tests/lint), PR Terraform plan, manual deploy, run-scenario, gitleaks
├── notebooks/
│   ├── bronze/                # Ingestion: Auto Loader (cloudFiles) → Delta
│   ├── silver/                # Quality: cleansing, dedup, sentinel handling
│   └── gold/
│       ├── gold_fleet_monitoring_enrichment.py  # Join + risk + DQ/quarantine + masking + drift + metrics
│       └── gold_dim_driver.py                    # SCD Type 2 driver→truck dimension
├── src/
│   ├── fleet_transforms/      # silver, gold (SQL builders + DQ suite), risk_model,
│   │                          # quality (expectations), observability, dimensions (SCD2), drift (PSI)
│   ├── fleet_governance/      # classification (GDPR Art. 9), masking (UC column masks), generate (docs)
│   ├── mock_generator/        # IoT simulation engine (intentional dirty-data injection)
│   ├── replay/                # Real-data replay: VED parsing, event-conditioned biometrics, producer
│   └── alerting/              # Push safety alerts to Slack + PagerDuty from the pipeline (ADR-009)
├── app/                       # Streamlit "Fleet Safety Command Center" (offline demo or live Databricks SQL)
├── data/ved/                  # Committed real VED sample (10 vehicles, 18 trips) + attribution
├── scripts/                   # fetch_ved.py — pull the full VED dataset (gitignored)
├── docs/
│   ├── adr/                   # ADR-001..009 (state, join window, BI, micro-batch, DQ, SCD2, masking, replay, alerting)
│   ├── governance/            # Generated risk model card + GDPR Art. 30 processing record
│   ├── architecture.md        # Mermaid diagrams
│   ├── RUNBOOK.md             # Ops: latency/cost, observability, incidents, recovery
│   └── SCALING.md             # What changes from 10 → 10,000 drivers
├── tests/                     # 161 tests (pure-Python + local PySpark)
├── databricks.yml             # DABs bundle: 2 jobs (mock + real-data replay), variables, targets
├── Makefile                   # Front door: `make help`
├── terraform.sh / bundle.sh / setup.sh   # Layer orchestrator / DABs bridge / local bootstrap
└── requirements*.txt
```
---

## 💎 The Medallion Journey (Data Engineering Deep-Dive)

**Visualizing the End-to-End Orchestration of the Data Pipeline**

> 🎥 **[ TO RE-RECORD ]** — *Databricks Job DAG (8 tasks)*
> Capture the `simulated_sensors_job` graph showing the 8 tasks and their dependencies:
> `generate_mock_{trackers,watches}` → `bronze_*` → `silver_*` → `gold_fleet_enrichment`, with
> `build_dim_driver` branching off `silver_trackers` in parallel with Gold.

> **Workflow Orchestration:** Independent parallel tracks for each data domain (Trackers & Wearables). Bronze and Silver run concurrently, converging at the Gold enrichment stage; the SCD2 `build_dim_driver` task runs in parallel with Gold. Tasks are decoupled, supporting independent retries and precise state monitoring.

**0. Data Sources (Simulation *and* the Real World)**
* **Mock engine:** Python producers with **intentional error injection** (null heart rates, sentinel speeds, malformed IDs, ~20% duplicates) to exercise the Silver rules.
* **Real-data replay:** `real_telemetry_job` streams genuine VED trips (real GPS, speeds, hard-braking events) through the identical contract; biometrics are simulated *conditioned on those real events* ([ADR-008](./docs/adr/ADR-008-real-data-replay.md)). Mock proves the defences; real data proves the pipeline.
* **Landing Zone:** AWS S3 landing zone & Unity Catalog Volumes (hybrid strategy).

> 🎥 **[ TO RE-RECORD ]** — *Landing zone (S3 / UC Volume)*
> Capture the raw CSV/JSON batches landing in the S3 path or the `raw_files` UC Volume.

**1. Bronze Layer (Automated Ingestion)**
* **Tool:** Databricks Auto Loader (`cloudFiles`).
* **Resilience:** Schema evolution + **rescued-data** column (`_rescued_data`) — malformed records are never lost.
* **Fault Tolerance:** Managed checkpointing via Unity Catalog Volumes → exactly-once-style, no reprocessing on restart.

> 🎥 **[ TO RE-RECORD ]** — *Bronze table + streaming checkpoints*
> Capture the `*_raw` Bronze Delta table and the checkpoint files in the `checkpoints` UC Volume.

> **The Rescue Pattern:** With `cloudFiles.rescuedDataColumn`, malformed IoT records are diverted to a hidden column for post-mortem analysis — zero data loss during high-velocity ingestion. The checkpoint metadata lives in a Volume isolated from the data layers, keeping a clean security boundary.

**2. Silver Layer (Quality Enforcement & Sanitization)**
* **Logic:** type casting, deduplication on `(device_id, event_timestamp)`, and standardization.
* **Sanitization:** prunes "ghost drivers" (`DRV_999`) and malformed IDs (`_ERR`, empty); nulls impossible sensor readings (GPS `(0,0)`, speed `-1`/`999`, heart rate `-999`/`0`/`>220`); normalizes status (`TRIM`/`UPPER`).

> 🎥 **[ TO RE-RECORD ]** — *Silver table (cleaned & conformed)*
> Capture a `*_clean` Silver table showing typed, deduplicated rows.

**3. Gold Layer (Business Intelligence & Risk Analytics)**
* **Technical challenge:** asynchronous stream correlation via a **±60s temporal join**.
* **Business value:** explainable risk scoring, hourly safety metrics, and alerts — each guarded by the declarative DQ suite and protected by enforced column masks.

> 🎥 **[ TO RE-RECORD ]** — *Gold `fleet_live_status` (the headline)*
> **Most important capture.** Show the table/dashboard **including the `risk_score`,
> `risk_primary_factor`, and the per-factor `risk_*_pts` columns** — that's what proves the
> "explainable by design" claim. Use the Streamlit dashboard, or the Catalog Explorer sample
> scrolled right to the risk columns. (Biometrics read as `NULL` for non-privileged principals
> due to column masks — capture as a member of the privileged group, or use the Streamlit view.)

> 🎥 **[ TO RE-RECORD ]** — *Gold safety metrics & alerts*
> Capture `driver_safety_metrics` (hourly aggregates) and/or `fleet_safety_alerts` (the alert log).

> **Live Fleet Status:** by joining tracker telemetry with biometric streams within the ±60s window, the system computes a risk score on the fly — a single source of truth for operational safety, decomposed into the factors that produced it.

---

## 🔍 Quality, Governance & Observability

Beyond the joins, the Gold stage wraps the enrichment with four cross-cutting concerns, each backed by a pure, unit-tested module under `src/` (the notebook only orchestrates):

* **Declarative data quality** — `fleet_live_status` is validated against a named expectation suite built from the risk model. `ERROR` violations are **quarantined** to `fleet_live_status_quarantine` (annotated with `_dq_failures`); the run fails only if an `ERROR` expectation was breached. ([ADR-005](./docs/adr/ADR-005-declarative-data-quality.md))
* **Enforced column masks** — special-category biometrics (NULL) and location (coarsened) are masked for principals outside the `fleet_safety_officers` group, derived from the classification so they can't drift — covering the live table, alerts, the quarantine side table, and the per-driver aggregates. ([ADR-007](./docs/adr/ADR-007-column-masking.md))
* **Risk-score drift** — PSI of the risk-score distribution vs. a baseline, surfaced as a WARN signal (suspect a recalibrated sensor before a real safety shift).
* **Pipeline self-metrics** — a tall, append-only `pipeline_metrics` fact for Grafana.

> 🎥 **[ TO RE-RECORD ]** — *`pipeline_metrics` + a quarantine example*
> Capture the `pipeline_metrics` table (row counts, `join_match_rate`, `risk_score_psi`,
> band distribution) and, optionally, a few rows of `fleet_live_status_quarantine` showing `_dq_failures`.

---

## 📈 Executive Observability
**Real-Time Fleet Health and Risk Monitoring Dashboard**

> 🎥 **[ TO RE-RECORD ]** — *Grafana dashboard*
> Capture the Grafana "pane of glass" over the serverless SQL Warehouse: risk leaderboard,
> live map, alerts, and the `pipeline_metrics` trend panels.

> **Data-Driven Decision Making:** Grafana transforms raw signals into a single pane of glass for fleet managers — surfacing dangerous correlations (physical driver stress during high-speed maneuvers) and the pipeline's own health over time.

---

## ⚙️ DevOps & Infrastructure as Code

**1. 🧰 The `make` front door**
A [`Makefile`](./Makefile) wraps the tooling in one discoverable interface (`make help`) and defines the CI gates in exactly one place:
```bash
make check                 # lint + fmt-check + test + govern-check (everything CI runs)
make plan LAYER=01_infra   # delegates to terraform.sh
make deploy | run          # delegates to bundle.sh
```

**2. 🚀 CI/CD Automation Pipeline**
GitHub Actions bridges Terraform and Databricks Asset Bundles: a PR plan workflow (sticky comments per layer), a local test-suite gate, gitleaks secret scanning, and a manual (`workflow_dispatch`) deploy that captures dynamic Terraform outputs (e.g. Service Principal IDs) and injects them into the bundle deploy.

> 🎥 **[ TO RE-RECORD ]** — *GitHub Actions run*
> Capture a green CI run (lint + 161 tests + govern-check) and/or the multi-job deploy workflow.

**3. 🛠️ The `terraform.sh` Orchestrator**
A custom utility that **automates secret injection** (fetches SPN credentials from AWS Secrets Manager → `TF_VAR_*`), manages per-layer backends, and provides lint/plan/apply/destroy across `01_infra`, `02_workspace`, and `03_unity_catalog`.

**4. ☁️ Modular Remote State Storage (AWS S3)**
Isolated state files per layer minimize the "blast radius" of changes; foundation resources stay protected during application-level updates.

> 🎥 **[ TO RE-RECORD ]** — *Modular remote state in S3*
> Capture the S3 state-bucket structure showing the isolated `dev/01-infra`, `dev/02-workspace`,
> `dev/03-unity-catalog` `terraform.tfstate` keys. **Scrub any visible AWS account ID / ARN.**

---

## 🚦 Operational Guide (Local Deployment & Lifecycle)

> The `Makefile` is the front door; the shell scripts below are what it calls (and what CI calls).

**1. Environment Setup & Bootstrapping**
```bash
make setup        # or: ./setup.sh   (creates the .venv test env + .env)
                  # ./setup.sh --connect additionally creates .venv-connect
                  # (Databricks Connect — kept separate: it conflicts with pyspark)
```

**2. Multi-Layer Infrastructure Deployment** (mandatory order)
```bash
make infra-up
# equivalently:
./terraform.sh 01_infra apply
./terraform.sh 02_workspace apply
./terraform.sh 03_unity_catalog apply
```

**3. Pipeline Orchestration**
```bash
make deploy       # ./bundle.sh deploy  — upload notebooks/src + register both jobs
make run          # ./bundle.sh run     — trigger the 8-task mock Medallion job
BUNDLE_JOB_NAME=real_telemetry_job make run   # trigger the real-data replay job
```

> 🖱️ **Or run it from GitHub with one click:** the **Run Fleet Pipeline** workflow
> (`workflow_dispatch`) offers a dropdown to pick the data scenario — *Simulated IoT sensors
> (mock data)* or *Real vehicle telemetry (VED replay)* — deploys the current bundle, and runs
> the matching job. Infrastructure provisioning stays in the separate manual deploy workflow.

**4. Automated Resource Teardown** (reverse order)
```bash
make infra-down
# equivalently:
./terraform.sh 03_unity_catalog destroy
./terraform.sh 02_workspace destroy
./terraform.sh 01_infra destroy
```

> 🎥 **[ TO RE-RECORD ]** — *State-aware teardown*
> Capture a clean `03_unity_catalog destroy` log validating that catalogs, schemas, and
> grants are purged in reverse-dependency order.

---

## 🚀 Future Roadmap & Scalability
The platform is designed for continuous evolution (see [docs/SCALING.md](./docs/SCALING.md)):
* **Delta Live Tables (DLT):** the declarative DQ expectations are written as SQL predicates precisely so they can be pushed into DLT `EXPECT` / Delta `CHECK` constraints at scale.
* **Continuous streaming:** if the freshness SLA tightens below the run interval, migrate the Gold join to a stateful stream-stream join with watermarks — the stateless SQL builders port directly ([ADR-004](./docs/adr/ADR-004-micro-batch-execution.md)).
* **Predictive safety:** Databricks Model Serving to predict driver fatigue from biometric aggregates.
* **Enhanced security:** fully private networking via AWS VPC PrivateLink.

## 🤝 Conclusion
A **Modern Data Stack** built on **Reliability, Security, and Observability** — Infrastructure as Code, Data as a Product, explainable analytics, and governance that is *enforced and checked in CI*, not just documented.

---

</div>
