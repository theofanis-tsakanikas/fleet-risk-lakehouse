# ==============================================================================
# 📊 LAYER 04 — AMAZON MANAGED GRAFANA (operational monitoring)
# ==============================================================================
# A standalone layer (its own remote state) so the Grafana workspace can be created and
# destroyed independently of the data platform. It queries the Databricks SQL Warehouse via
# the Databricks plugin (configured in-app with the read-only BI SPN) to visualise the
# `pipeline_metrics` fact. Login is via AWS IAM Identity Center.

module "grafana" {
  source = "../modules/aws_grafana"

  environment    = var.environment
  workspace_name = var.workspace_name
  admin_user_id  = var.grafana_admin_user_id
}
