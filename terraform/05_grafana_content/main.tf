# ==============================================================================
# 📊 LAYER 05 — Infinity datasource + the pipeline observability dashboard
# ==============================================================================

# --- 1. The Databricks-over-Infinity datasource -------------------------------
# The OSS Infinity plugin (installed in layer 04) authenticates to Databricks with OAuth2
# machine-to-machine (client credentials) using the read-only BI SPN, then POSTs SQL to the
# Databricks SQL Statement Execution REST API. Because the SPN is only a `data_analysts` member
# (not in fleet_safety_officers), every query it runs already respects the UC column masks —
# Grafana sees risk scores / drift / counts, never raw Art. 9 biometrics.
resource "grafana_data_source" "databricks" {
  type = "yesoreyeram-infinity-datasource"
  name = "Databricks SQL (Infinity)"

  json_data_encoded = jsonencode({
    auth_method = "oauth2"
    oauth2 = {
      oauth2_type = "client_credentials"
      client_id   = local.bi_client_id
      token_url   = "${local.databricks_host}/oidc/v1/token"
      scopes      = ["all-apis"]
    }
    # Allowlist both the API host and the token host (same workspace host here). Required once
    # auth is configured, else Infinity rejects the call with "host not allowed".
    allowedHosts = [local.databricks_host]
  })

  secure_json_data_encoded = jsonencode({
    oauth2ClientSecret = local.bi_client_secret
  })
}

# --- 2. Panel definitions -----------------------------------------------------
# Tall pipeline_metrics (run_id, captured_at, stage, metric, value). Each panel is one SQL query
# over the latest run; the backend parser's column selectors map Databricks' positional
# `result.data_array` (arrays of strings) into named, numeric columns.
locals {
  # All distribution/null panels pin to the newest run so their bars are internally consistent.
  latest_run = "run_id = (SELECT run_id FROM ${local.metrics_table} ORDER BY captured_at DESC LIMIT 1)"

  # The backend parser runs server-side (unlike UQL, which only parses in the browser and so
  # returns nothing over /api/ds/query or in alerting). It maps positional cells of Databricks'
  # `result.data_array` into named, typed columns via `selector` = the array index.
  cols_value        = [{ selector = "0", text = "value", type = "number" }]
  cols_metric_value = [{ selector = "0", text = "metric", type = "string" }, { selector = "1", text = "value", type = "number" }]
  cols_stage_metric = [{ selector = "0", text = "stage", type = "string" }, { selector = "1", text = "metric", type = "string" }, { selector = "2", text = "value", type = "number" }]
  # For trend panels: captured_at (as a time field) + the metric label + its value across runs.
  cols_time_series = [{ selector = "0", text = "time", type = "timestamp" }, { selector = "1", text = "metric", type = "string" }, { selector = "2", text = "value", type = "number" }]

  panel_specs = [
    {
      title   = "Join match rate (latest)"
      ptype   = "stat", unit = "percentunit", decimals = 2
      x       = 0, y = 0, w = 6, h = 4
      sql     = "SELECT value FROM ${local.metrics_table} WHERE metric = 'join_match_rate' ORDER BY captured_at DESC LIMIT 1"
      columns = local.cols_value
    },
    {
      title   = "Live status rows (latest)"
      ptype   = "stat", unit = "short", decimals = 0
      x       = 6, y = 0, w = 6, h = 4
      sql     = "SELECT value FROM ${local.metrics_table} WHERE metric = 'live_status_rows' ORDER BY captured_at DESC LIMIT 1"
      columns = local.cols_value
    },
    {
      title   = "Quarantined rows (latest)"
      ptype   = "stat", unit = "short", decimals = 0
      x       = 12, y = 0, w = 6, h = 4
      sql     = "SELECT value FROM ${local.metrics_table} WHERE metric = 'live_quarantined_rows' ORDER BY captured_at DESC LIMIT 1"
      columns = local.cols_value
    },
    {
      title   = "Risk-score PSI / drift (latest)"
      ptype   = "stat", unit = "short", decimals = 2
      x       = 18, y = 0, w = 6, h = 4
      sql     = "SELECT value FROM ${local.metrics_table} WHERE metric = 'risk_score_psi' ORDER BY captured_at DESC LIMIT 1"
      columns = local.cols_value
    },
    {
      title   = "Risk band distribution (latest run)"
      ptype   = "barchart", unit = "short", decimals = 0
      x       = 0, y = 4, w = 12, h = 9
      sql     = "SELECT metric, value FROM ${local.metrics_table} WHERE metric LIKE 'dist_band_%' AND ${local.latest_run} ORDER BY metric"
      columns = local.cols_metric_value
    },
    {
      title   = "Sensor null rates (latest run)"
      ptype   = "bargauge", unit = "percentunit", decimals = 3
      x       = 12, y = 4, w = 12, h = 9
      sql     = "SELECT metric, value FROM ${local.metrics_table} WHERE metric LIKE '%null_rate%' AND ${local.latest_run} ORDER BY metric"
      columns = local.cols_metric_value
    },
    {
      title   = "Join match rate over runs"
      ptype   = "timeseries", unit = "percentunit", decimals = 2
      x       = 0, y = 13, w = 12, h = 8
      sql     = "SELECT CAST(captured_at AS STRING), metric, value FROM ${local.metrics_table} WHERE metric = 'join_match_rate' ORDER BY captured_at"
      columns = local.cols_time_series
    },
    {
      title   = "Risk-score PSI / drift over runs"
      ptype   = "timeseries", unit = "short", decimals = 2
      x       = 12, y = 13, w = 12, h = 8
      sql     = "SELECT CAST(captured_at AS STRING), metric, value FROM ${local.metrics_table} WHERE metric = 'risk_score_psi' ORDER BY captured_at"
      columns = local.cols_time_series
    },
    {
      title   = "All pipeline metrics (latest run)"
      ptype   = "table", unit = "short", decimals = 2
      x       = 0, y = 21, w = 24, h = 9
      sql     = "SELECT stage, metric, value FROM ${local.metrics_table} WHERE ${local.latest_run} ORDER BY metric"
      columns = local.cols_stage_metric
    },
  ]

  panels = [for i, p in local.panel_specs : {
    id         = i + 1
    title      = p.title
    type       = p.ptype
    gridPos    = { x = p.x, y = p.y, w = p.w, h = p.h }
    datasource = { type = "yesoreyeram-infinity-datasource", uid = grafana_data_source.databricks.uid }
    # jsondecode(jsonencode(...)) keeps the ternary branches the same (string) type — the objects
    # differ in shape per panel type, which a bare ?: rejects.
    fieldConfig = {
      # Draw points always so a single run (one data point) is still visible on the line.
      defaults = jsondecode(p.ptype == "timeseries"
        ? jsonencode({ unit = p.unit, decimals = p.decimals, custom = { drawStyle = "line", showPoints = "always", lineWidth = 2, pointSize = 7, spanNulls = true } })
        : jsonencode({ unit = p.unit, decimals = p.decimals })
      )
      overrides = []
    }
    # Stat panels reduce to one value; bar gauges must show every row as its own labelled bar
    # (values = true), else Grafana collapses the frame to a single bar. Bar chart / table ignore it.
    options = jsondecode(
      p.ptype == "stat" ? jsonencode({ reduceOptions = { calcs = ["lastNotNull"] }, colorMode = "value", graphMode = "none" }) :
      p.ptype == "bargauge" ? jsonencode({ reduceOptions = { values = true }, displayMode = "gradient", orientation = "horizontal" }) :
      p.ptype == "barchart" ? jsonencode({ xField = "metric", showValue = "always" }) :
      jsonencode({})
    )
    targets = [{
      refId         = "A"
      datasource    = { type = "yesoreyeram-infinity-datasource", uid = grafana_data_source.databricks.uid }
      type          = "json"
      source        = "url"
      parser        = "backend"
      format        = p.ptype == "timeseries" ? "timeseries" : "table"
      root_selector = "result.data_array"
      columns       = p.columns
      url           = local.statements_url
      url_options = {
        method            = "POST"
        body_type         = "raw"
        body_content_type = "application/json"
        data = jsonencode({
          warehouse_id    = local.warehouse_id
          statement       = p.sql
          wait_timeout    = "50s"
          on_wait_timeout = "CANCEL"
          disposition     = "INLINE"
          format          = "JSON_ARRAY"
        })
      }
    }]
  }]
}

# --- 3. The dashboard ---------------------------------------------------------
resource "grafana_dashboard" "pipeline_observability" {
  config_json = jsonencode({
    uid           = "fleet-pipeline-obs"
    title         = "Fleet Risk Lakehouse — Pipeline Observability"
    tags          = ["fleet-risk-lakehouse", "observability"]
    timezone      = "browser"
    schemaVersion = 39
    version       = 1
    refresh       = "5m"
    time          = { from = "now-30d", to = "now" }
    templating    = { list = [] }
    annotations   = { list = [] }
    panels        = local.panels
  })

  overwrite = true
}
