# ADR-003: Databricks SQL Warehouse as the Grafana Query Backend

**Date:** 2024-06  
**Status:** Accepted

---

## Context

Grafana requires a queryable SQL endpoint over the Gold layer Delta tables (`fleet_live_status`, `driver_safety_metrics`, `fleet_safety_alerts`) to power the real-time fleet monitoring dashboard. Three options were evaluated:

**Option A — All-purpose cluster (long-running)**  
A standard Databricks cluster kept alive as a persistent JDBC/ODBC target. Always warm, so Grafana queries return immediately. Cost: a minimum-configuration cluster (2 workers) runs continuously at ~$0.25/DBU, incurring significant idle cost.

**Option B — Databricks SQL Warehouse (serverless)**  
Purpose-built BI compute with automatic start/stop, automatic scaling, Unity Catalog RBAC enforcement at the query boundary, and Grafana native plugin support. Serverless tier eliminates VM provisioning delays. Cost: billed only when queries run, with a configurable auto-stop timeout.

**Option C — Delta Sharing to an external engine**  
Export Gold tables via Delta Sharing to a self-managed Trino or Redshift cluster. Grafana queries the external engine. Adds an operational sync layer and introduces potential replication lag incompatible with the real-time dashboard requirement.

---

## Decision

Use a **Databricks Serverless PRO SQL Warehouse** (`serverless_bi-dev`), provisioned via Terraform in the `databricks_workspace_config` module (layer `02_workspace`).

Configuration chosen:

| Parameter | Value | Rationale |
|---|---|---|
| `cluster_size` | `2X-Small` | 10 drivers, low-cardinality Gold tables; 2X-Small handles concurrent Grafana panels |
| `warehouse_type` | `PRO` | Required for serverless compute and Lakehouse Federation |
| `enable_serverless_compute` | `true` | No VM provisioning; ~10–20s resume vs. ~3–5min cluster start |
| `auto_stop_mins` | `10` | Eliminates idle cost outside business hours |
| `max_num_clusters` | `2` | Allows scale-out under simultaneous dashboard refresh load |
| Access | `data_engineers`, `data_analysts` at `CAN_USE` | Least-privilege; groups defined in layer `01_infra` |

Grafana connects via the **Databricks data source plugin** using:
- **Host**: `DATABRICKS_HOST` (workspace URL)
- **HTTP Path**: from the warehouse's Connection Details tab in the Databricks UI
- **Auth**: SPN OAuth (client ID + secret) or a scoped Personal Access Token

Unity Catalog RBAC is enforced at the warehouse boundary — a Grafana query running as a `data_analyst` SPN cannot read beyond the `SELECT` grants on `fleet_dev.operations.*`.

---

## Consequences

**Benefits**

- No cluster management: the warehouse is provisioned by Terraform and requires zero operational intervention once deployed.
- Cost-controlled: the 10-minute auto-stop prevents idle billing between dashboard refresh cycles.
- UC RBAC enforced at query time: Grafana does not bypass Unity Catalog access control.
- Serverless cold start (~10–20 seconds) is acceptable for a dashboard that refreshes every 30–60 seconds — the first panel load may be slow, but subsequent queries within the auto-stop window hit a warm warehouse.
- PRO warehouse tier enables Lakehouse Federation and Delta Sharing should those features be needed in the future roadmap.

**Trade-offs**

- Serverless PRO DBU cost is higher than Standard per compute-minute. Justified by eliminating cluster management overhead and the auto-stop mechanism preventing continuous billing.
- A Grafana user who opens the dashboard after a period of inactivity will experience a ~10–20 second delay on first load as the warehouse resumes. This is a UX trade-off accepted in exchange for cost control.
- Grafana's Databricks plugin must be installed in the Grafana instance (not bundled by default in Grafana OSS). See the [plugin page](https://grafana.com/grafana/plugins/grafana-databricks-datasource/) for installation steps.
