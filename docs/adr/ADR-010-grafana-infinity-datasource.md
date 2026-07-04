# ADR-010: Grafana observability via the OSS Infinity datasource (not the Enterprise Databricks plugin)

- **Status:** Accepted
- **Date:** 2026-07-05
- **Supersedes the connection mechanism in:** [ADR-003](ADR-003-sql-warehouse-grafana.md) (the SQL
  Warehouse stays the query backend; only *how* Grafana reaches it changes)

## Context

We want Amazon Managed Grafana (AMG, [layer 04](../../terraform/04_grafana/)) to trend the
`fleet_dev.metadata.pipeline_metrics` observability fact (join match rate, quarantine count,
risk-score drift/PSI, band distribution, sensor null rates) over the Databricks SQL Warehouse — and
we want it provisioned **as code**, not clicked together in the UI.

The obvious path — the official **Grafana Databricks data source plugin** — is an **Enterprise**
plugin. On AMG, Enterprise plugins require the **Enterprise plugins upgrade at +$45 per active user
per month**, on top of the ~$9 base. For a portfolio/demo workspace that is created and destroyed on
demand, that is not worth it. (This corrects the earlier assumption in ADR-003 / CLAUDE.md that you
"just install the Databricks plugin".)

## Decision

Query Databricks from Grafana through the **free, OSS [Infinity datasource](https://grafana.com/grafana/plugins/yesoreyeram-infinity-datasource/)**
instead:

1. **Transport** — Infinity POSTs SQL to the Databricks **SQL Statement Execution REST API**
   (`POST /api/2.0/sql/statements`, `wait_timeout=50s`, `disposition=INLINE`, `format=JSON_ARRAY`)
   against the layer-02 warehouse id.
2. **Auth** — **OAuth2 machine-to-machine (client credentials)** with the read-only BI SPN
   (`grafana-bi-reader-dev`): token URL `…/oidc/v1/token`, scope `all-apis`. Because that SPN is only
   a `data_analysts` member (not in `fleet_safety_officers`), every query already respects the Unity
   Catalog **column masks** — Grafana sees risk scores / drift / counts, **never raw Art. 9
   biometrics** ([ADR-007](ADR-007-column-masking.md)).
3. **Parsing** — the **backend** parser (server-side) with positional column selectors maps
   Databricks' `result.data_array` (arrays of strings) into named, typed columns. The frontend **UQL**
   parser was rejected: it only runs in the browser, so it returns nothing over `/api/ds/query` or in
   alerting.
4. **Provisioned as code, split across two layers** to avoid the "provider configured from a
   not-yet-created resource" bootstrap problem:
   - **Layer 04** creates the workspace, sets `configuration.plugins.pluginAdminEnabled = true`,
     creates an **ADMIN service account + token**, and installs the Infinity plugin via a
     `null_resource` `local-exec curl` to the Grafana HTTP API (AMG has no Terraform-native plugin
     resource; `grafana_plugin*` is Grafana-Cloud only). It emits the token as a sensitive output.
   - **Layer 05** ([`05_grafana_content`](../../terraform/05_grafana_content/)) reads that token from
     layer 04's remote state (so it is a *known* value at plan time), configures the `grafana`
     provider, and declares the Infinity `grafana_data_source` + the `grafana_dashboard` (9 panels:
     stat / barchart / bargauge / timeseries / table).
5. **Grant** — `data_analysts` get `USE_SCHEMA + SELECT` on `fleet_dev.metadata` (layer 03) so the BI
   SPN can read `pipeline_metrics`. That schema holds only the operational fact table (no biometrics);
   the checkpoint *volume* stays engineer-only.

## Consequences

**Positive**
- **$0 beyond the base AMG** — no Enterprise licence.
- **GDPR posture preserved by construction** — the same masked read path as Streamlit; no special-
  category data leaves Databricks.
- **Fully declarative** — datasource + dashboards live in Terraform; a single `apply` per layer
  reproduces them. Backend parsing also makes the same queries usable for Grafana alerting later.

**Negative / caveats**
- The **service-account token expires after 30 days** (the AMG maximum). Rotate by re-applying layer
  04 (the token resource is replaced) and then layer 05.
- **Plugin install is imperative** (`null_resource` + curl) rather than a first-class resource — the
  one non-declarative seam, guarded to be idempotent ("already installed" is treated as success).
- **Warehouse cold start** (~20–30s) can approach the 50s statement wait on the first query after
  idle; occasional first-render lag is expected.
- Two layers instead of one, and layer 05 now depends on the remote state of layers 01, 02 and 04.

## Alternatives considered

- **Enterprise Databricks plugin** — cleanest UX, but +$45/user/mo on AMG. Rejected on cost.
- **Frontend UQL / JSONata parsing** — works in the browser but returns nothing server-side
  (`/api/ds/query`, alerting). Rejected for the backend parser.
- **Single layer** — blocked by the provider-bootstrap problem (a provider cannot be configured from
  a token created in the same apply); a two-stage `-target` apply is fragile. Rejected for the
  two-layer split.
- **Push metrics to CloudWatch** and use the native CloudWatch datasource — would need the pipeline to
  emit CloudWatch metrics and drops the SQL-over-lakehouse story. Rejected as heavier and off-pattern.
