# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

### Changed
- `requirements.txt` now includes `pre-commit`.

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
