# ==============================================================================
# 📊 LAYER 05 — "Fleet Operations" dashboard (business view over the Gold layer)
# ==============================================================================
# A second dashboard alongside the pipeline-observability one. It reads the Gold `operations`
# tables through the same Infinity datasource, so it respects the UC masks: risk scores, alert
# types, coarse (masked) truck coordinates and risk factors are shown; raw Art. 9 biometrics are
# not (they read NULL for the BI SPN). See ADR-007 / ADR-010.

locals {
  ops_schema = "${var.catalog}.operations"

  # One reusable Infinity backend target per query (SQL → named, typed columns).
  ops_queries = {
    geomap = {
      sql = "SELECT latitude, longitude, CAST(risk_score AS DOUBLE), driver_id FROM ${local.ops_schema}.fleet_live_status WHERE latitude IS NOT NULL"
      columns = [{ selector = "0", text = "latitude", type = "number" }, { selector = "1", text = "longitude", type = "number" },
      { selector = "2", text = "risk_score", type = "number" }, { selector = "3", text = "driver_id", type = "string" }]
    }
    leaderboard = {
      sql     = "SELECT driver_id, CAST(risk_score AS DOUBLE) FROM ${local.ops_schema}.fleet_live_status ORDER BY risk_score DESC"
      columns = [{ selector = "0", text = "driver_id", type = "string" }, { selector = "1", text = "risk_score", type = "number" }]
    }
    alerts_by_type = {
      sql     = "SELECT alert_type, CAST(COUNT(*) AS DOUBLE) FROM ${local.ops_schema}.fleet_safety_alerts GROUP BY alert_type ORDER BY 2 DESC"
      columns = [{ selector = "0", text = "alert_type", type = "string" }, { selector = "1", text = "count", type = "number" }]
    }
    primary_factor = {
      sql     = "SELECT risk_primary_factor, CAST(COUNT(*) AS DOUBLE) FROM ${local.ops_schema}.fleet_live_status GROUP BY risk_primary_factor ORDER BY 2 DESC"
      columns = [{ selector = "0", text = "risk_primary_factor", type = "string" }, { selector = "1", text = "count", type = "number" }]
    }
    kpi_avg_risk      = { sql = "SELECT CAST(ROUND(AVG(risk_score), 1) AS DOUBLE) FROM ${local.ops_schema}.fleet_live_status", columns = local.cols_value }
    kpi_max_risk      = { sql = "SELECT CAST(MAX(risk_score) AS DOUBLE) FROM ${local.ops_schema}.fleet_live_status", columns = local.cols_value }
    kpi_active_alerts = { sql = "SELECT CAST(COUNT(*) AS DOUBLE) FROM ${local.ops_schema}.fleet_safety_alerts", columns = local.cols_value }
    kpi_trucks        = { sql = "SELECT CAST(COUNT(DISTINCT truck_id) AS DOUBLE) FROM ${local.ops_schema}.fleet_live_status", columns = local.cols_value }
  }

  ops_target = { for k, s in local.ops_queries : k => {
    refId         = "A"
    datasource    = { type = "yesoreyeram-infinity-datasource", uid = grafana_data_source.databricks.uid }
    type          = "json"
    source        = "url"
    parser        = "backend"
    format        = "table"
    root_selector = "result.data_array"
    columns       = s.columns
    url           = local.statements_url
    url_options = {
      method            = "POST"
      body_type         = "raw"
      body_content_type = "application/json"
      data = jsonencode({
        warehouse_id    = local.warehouse_id, statement = s.sql, wait_timeout = "50s"
        on_wait_timeout = "CANCEL", disposition = "INLINE", format = "JSON_ARRAY"
      })
    }
  } }

  ds_ref = { type = "yesoreyeram-infinity-datasource", uid = grafana_data_source.databricks.uid }

  # Risk colouring reused by the KPI gauges and the map markers: green < 50 < yellow < 75 < red.
  risk_thresholds = { mode = "absolute", steps = [
    { color = "green", value = null }, { color = "yellow", value = 50 }, { color = "red", value = 75 }
  ] }

  # "Higher is better" colouring for the join-match-rate gauge (0–1): red < 0.8 < yellow < 0.95 < green.
  match_thresholds = { mode = "absolute", steps = [
    { color = "red", value = null }, { color = "yellow", value = 0.8 }, { color = "green", value = 0.95 }
  ] }

  # Shared gauge display options (radial arc with coloured threshold markers).
  gauge_options = { reduceOptions = { calcs = ["lastNotNull"] }, showThresholdLabels = false, showThresholdMarkers = true, orientation = "auto" }
}

resource "grafana_dashboard" "fleet_operations" {
  overwrite = true
  config_json = jsonencode({
    uid           = "fleet-operations"
    title         = "Fleet Risk Lakehouse — Fleet Operations"
    tags          = ["fleet-risk-lakehouse", "operations"]
    timezone      = "browser"
    schemaVersion = 39
    version       = 1
    refresh       = "5m"
    time          = { from = "now-30d", to = "now" }
    templating    = { list = [] }
    annotations   = { list = [] }
    panels = [
      # --- Row 0: KPI stats ---------------------------------------------------
      {
        id          = 1, title = "Avg fleet risk", type = "gauge", datasource = local.ds_ref
        gridPos     = { x = 0, y = 0, w = 6, h = 5 }, targets = [local.ops_target["kpi_avg_risk"]]
        fieldConfig = { defaults = { unit = "short", decimals = 1, min = 0, max = 100, color = { mode = "thresholds" }, thresholds = local.risk_thresholds }, overrides = [] }
        options     = local.gauge_options
      },
      {
        id          = 2, title = "Max driver risk", type = "gauge", datasource = local.ds_ref
        gridPos     = { x = 6, y = 0, w = 6, h = 5 }, targets = [local.ops_target["kpi_max_risk"]]
        fieldConfig = { defaults = { unit = "short", decimals = 1, min = 0, max = 100, color = { mode = "thresholds" }, thresholds = local.risk_thresholds }, overrides = [] }
        options     = local.gauge_options
      },
      {
        id          = 3, title = "Active safety alerts", type = "stat", datasource = local.ds_ref
        gridPos     = { x = 12, y = 0, w = 6, h = 5 }, targets = [local.ops_target["kpi_active_alerts"]]
        fieldConfig = { defaults = { unit = "short", decimals = 0, color = { mode = "fixed", fixedColor = "orange" } }, overrides = [] }
        options     = { reduceOptions = { calcs = ["lastNotNull"] }, colorMode = "value", graphMode = "none" }
      },
      {
        id          = 4, title = "Trucks tracked", type = "stat", datasource = local.ds_ref
        gridPos     = { x = 18, y = 0, w = 6, h = 5 }, targets = [local.ops_target["kpi_trucks"]]
        fieldConfig = { defaults = { unit = "short", decimals = 0, color = { mode = "fixed", fixedColor = "blue" } }, overrides = [] }
        options     = { reduceOptions = { calcs = ["lastNotNull"] }, colorMode = "value", graphMode = "none" }
      },
      # --- Row 1: map + leaderboard ------------------------------------------
      {
        id          = 5, title = "Truck positions — colour = risk (location is masked / coarse)", type = "geomap", datasource = local.ds_ref
        gridPos     = { x = 0, y = 5, w = 16, h = 12 }, targets = [local.ops_target["geomap"]]
        fieldConfig = { defaults = { color = { mode = "thresholds" }, thresholds = local.risk_thresholds }, overrides = [] }
        options = {
          view     = { id = "coords", lat = 38.0, lon = 23.75, zoom = 8, allLayers = true }
          controls = { showZoom = true, mouseWheelZoom = true, showAttribution = true, showScale = false }
          # NOTE: Amazon Managed Grafana pins its own basemap tiles and sets
          # geomapDisableCustomBaseLayer = true at the instance level, so ANY custom basemap set here
          # (dark / no-labels / XYZ) is ignored — the map always renders with AMG's light OSM tiles
          # (local-language place labels). We keep the default; a dark, label-free base would require
          # a community Leaflet map-panel plugin (deliberately not pursued to keep the stack simple).
          basemap = { type = "default", name = "Basemap" }
          layers = [{
            type     = "markers"
            name     = "Trucks"
            location = { mode = "coords", latitude = "latitude", longitude = "longitude" }
            config = {
              showLegend = true
              style = {
                size       = { fixed = 7, field = "risk_score", min = 5, max = 16 }
                color      = { fixed = "dark-red", field = "risk_score" }
                opacity    = 0.75
                symbol     = { mode = "fixed", fixed = "img/icons/marker/circle.svg" }
                text       = { field = "driver_id", fixed = "" }
                textConfig = { fontSize = 11, offsetX = 0, offsetY = -12, textAlign = "center", textBaseline = "middle" }
              }
            }
          }]
        }
      },
      {
        id          = 6, title = "Risk leaderboard (per driver)", type = "barchart", datasource = local.ds_ref
        gridPos     = { x = 16, y = 5, w = 8, h = 12 }, targets = [local.ops_target["leaderboard"]]
        fieldConfig = { defaults = { unit = "short", decimals = 1, color = { mode = "thresholds" }, thresholds = local.risk_thresholds }, overrides = [] }
        options     = { xField = "driver_id", orientation = "horizontal", showValue = "always" }
      },
      # --- Row 2: distributions ----------------------------------------------
      {
        id          = 7, title = "Alerts by type", type = "piechart", datasource = local.ds_ref
        gridPos     = { x = 0, y = 17, w = 12, h = 8 }, targets = [local.ops_target["alerts_by_type"]]
        fieldConfig = { defaults = { unit = "short", decimals = 0 }, overrides = [] }
        options     = { reduceOptions = { values = true }, pieType = "donut", displayLabels = ["name", "value"], legend = { displayMode = "list", placement = "right" } }
      },
      {
        id          = 8, title = "Risk primary factor (per driver)", type = "piechart", datasource = local.ds_ref
        gridPos     = { x = 12, y = 17, w = 12, h = 8 }, targets = [local.ops_target["primary_factor"]]
        fieldConfig = { defaults = { unit = "short", decimals = 0 }, overrides = [] }
        options     = { reduceOptions = { values = true }, pieType = "pie", displayLabels = ["name", "value"], legend = { displayMode = "list", placement = "right" } }
      },
    ]
  })
}
