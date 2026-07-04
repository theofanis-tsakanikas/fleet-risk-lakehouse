# ADR-001: 3-Layer Terraform with Isolated Remote State

**Date:** 2024-06  
**Status:** Accepted

---

## Context

The platform requires three categories of cloud resources with hard dependency ordering:

1. **AWS foundation** — S3 buckets, IAM roles, Secrets Manager, Databricks Service Principal (SPN), Unity Catalog Metastore, and Databricks Workspace. These must exist before anything else can be created.
2. **Workspace configuration** — SQL Warehouse, metastore-level grants. Requires a running Workspace with a known URL and a valid SPN.
3. **Unity Catalog governance** — Storage credentials, external locations, catalogs, schemas, volumes. Requires the Workspace to be configured with an authorized SPN and the IAM data-lake role to already exist.

A monolithic Terraform configuration would place all three categories in a single state file. Any change to a Unity Catalog schema (the most frequent change during development) would require locking and re-evaluating all AWS and Workspace resources in a single plan. This increases plan time, blast radius, and the risk of inadvertently destroying foundational infrastructure when the only intent was to modify an analytics-layer object.

---

## Decision

Separate the platform into three independent Terraform layers, each with its own S3 remote state backend key:

| Layer | S3 state key | Manages |
|---|---|---|
| `01_infra` | `dev/01-infra/terraform.tfstate` | S3 buckets, IAM roles, Secrets Manager, SPN, Metastore, Workspace |
| `02_workspace` | `dev/02-workspace/terraform.tfstate` | SQL Warehouse, metastore-level privilege grants |
| `03_unity_catalog` | `dev/03-unity-catalog/terraform.tfstate` | Storage credentials, external locations, catalogs, schemas, volumes, grants |

All three state files live in the same S3 bucket (`fleet-risk-lakehouse-tfstate-eu-central-1`) with encryption enabled, but each has an independent lock.

**Cross-layer wiring** uses `data "terraform_remote_state"` (read-only): layers `02_workspace` and `03_unity_catalog` read `workspace_url`, `metastore_id`, `datalake_role_arn`, and `secrets_manager_id` from layer `01_infra`'s last-applied state. They do not use module composition or share a common provider block — they depend only on the outputs of the previously applied layer.

**SPN credential injection** is handled by `terraform.sh`: it reads the `secrets_manager_id` output from layer `01_infra`, calls `aws secretsmanager get-secret-value`, and exports `TF_VAR_spn_client_id` / `TF_VAR_spn_client_secret` into the shell. This keeps credentials out of `.tfvars` files and version control entirely.

---

## Consequences

**Benefits**

- **Blast radius isolation.** A failed or partial destroy of `03_unity_catalog` cannot corrupt the `01_infra` state. An AWS IAM policy change in `01_infra` does not lock or require re-planning of the Unity Catalog objects in `03_unity_catalog`.
- **Independent lifecycle.** Data engineers can iterate on UC governance objects (add a schema, change a grant) with a fast `03_unity_catalog` plan/apply cycle without touching AWS or Workspace resources.
- **Faster CI plans.** The PR plan workflow runs each layer independently; the most frequently changed layer (`03_unity_catalog`) produces a plan in under a minute.
- **Zero credentials in version control.** The SPN secret is stored only in AWS Secrets Manager and injected at runtime. No `.tfvars` files hold secrets.

**Trade-offs**

- A strict apply and destroy order must be followed (01 → 02 → 03 for apply; reverse for destroy). Skipping the order causes authentication failures or unresolvable remote state reads.
- Cross-layer changes (e.g., a new IAM role needed by a new UC external location) require two separate `apply` runs in two separate layer directories.
- The `terraform.sh` orchestrator is a required operational dependency. Running `terraform` directly in a layer directory without first running `terraform.sh` will produce empty `TF_VAR_spn_*` variables and fail at provider initialization.
