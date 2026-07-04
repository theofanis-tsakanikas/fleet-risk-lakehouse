# ==============================================================================
# 📊 LAYER 05 — OUTPUTS
# ==============================================================================

output "datasource_uid" {
  description = "UID of the Databricks-over-Infinity datasource"
  value       = grafana_data_source.databricks.uid
}

output "dashboard_url" {
  description = "Path to the pipeline observability dashboard (append to the Grafana endpoint)"
  value       = grafana_dashboard.pipeline_observability.url
}
