# Deep-Dive Video — Plan (the long version)

**Length:** ~3–4 min · **Voiceover** + captions · for technical viewers / interviewers.
Linked from the hero as "Watch the full walkthrough".

## Why a second cut
The hero sells the *outcome* (fleet safety) in 70 seconds. The deep-dive proves the *how* — the
Medallion design, the asynchronous stream correlation, and the IaC/governance that make it
production-grade. This is where the senior signal lives, and where a voiceover earns its place.

## Tone
Calm, confident, technical-but-clear. Explain **decisions and why**, not line-by-line code.

## Structure (≈7 sections)

### 1. Cold open (0:00–0:15)
- Same hook as the hero (the risk map + leaderboard).
- **VO:** "This is a real-time fleet-safety lakehouse. It turns raw GPS and driver biometrics into a live risk score — and the whole platform is built as Infrastructure-as-Code. Here's how."

### 2. The problem (0:15–0:45)
- **Screen:** simple diagram — two independent data sources (GPS trackers, biometric watches), arriving asynchronously, dirty.
- **VO points:** fleet safety is reactive — you learn about risk after an incident. The data exists (telemetry + wearables) but it's two messy, unsynchronised streams. The hard part isn't the dashboard — it's correlating them reliably and trusting the result.

### 3. Medallion architecture (0:45–1:30) — the engineering spine
- **Screen:** the Bronze → Silver → Gold flow; show a Silver cleansing snippet and the Gold SQL.
- **VO points:**
  - **Bronze:** Auto Loader ingests both raw streams from S3, schema-on-read, append-only.
  - **Silver:** dedup, range filters, null handling, flatten nested watch metrics — ~20% of raw is malformed (bad IDs, sentinel speeds, null heart-rate) and gets dropped here.
  - **Gold:** the business layer — the temporal join + the risk score + the alert log.

### 4. The asynchronous correlation (1:30–2:10) — the clever bit
- **Screen:** the Driver Drill-down chart; overlay the ±60s window concept.
- **VO points:** the two streams don't tick together, so a naive join loses everything. A **±60-second temporal join** aligns a driver's GPS event with the nearest biometric reading (ADR-002). The **risk score** is a deliberate, weighted model — speed 40%, stress 35%, heart-rate 25%, capped at 100 — not a magic number. And every Gold write is **data-quality gated**: the enriched view must be non-empty, no null business keys, risk strictly within [0,100].

### 5. Infrastructure as Code + CI/CD (2:10–2:55) — production proof
- **Screen:** the three Terraform layers, `databricks.yml`, a green GitHub Actions run, the sticky `plan` PR comment.
- **VO points:** three isolated Terraform layers (foundation / workspace / governance) with per-layer remote state and automated secret injection (ADR-001). The pipeline ships via **Databricks Asset Bundles**; GitHub Actions does full `apply` on merge and posts a Terraform `plan` on every PR. Nothing is click-ops.

### 6. Governance & observability (2:55–3:25)
- **Screen:** Unity Catalog grants; the Grafana dashboard backed by the serverless SQL Warehouse.
- **VO points:** **Unity Catalog** gives fine-grained, auditable access control across the lakehouse. The executive dashboards read from a **serverless SQL Warehouse** (ADR-003) — the same Gold tables the Command Center reads.

### 7. Close (3:25–3:50)
- **Screen:** end card + your name / GitHub.
- **VO points (honest framing):** "This is a portfolio-grade lakehouse on synthetic-but-faithful data. What it demonstrates: Medallion data engineering on Spark, asynchronous stream correlation, and the IaC, CI/CD and governance that make a data platform production-ready." Then the stack: Databricks · Spark Structured Streaming · Delta · Unity Catalog · Terraform · GitHub Actions.

## Production notes
- Record screen B-roll generously; pace the screen to the VO, not the reverse.
- A clean architecture **diagram** for sections 2–4 lifts the whole thing.
- Reuse the hero's Command Center clips where they fit.
- Keep captions as a subtitle track (accessibility + muted viewing).

## What NOT to do
- Don't turn it into a notebook read-through — stay at "decisions + why".
- Don't claim it monitors a live fleet — it's the analytics platform on faithful demo data.
- Don't exceed ~4 min.
