# ==============================================================================
# 📊 DATABRICKS WORKSPACE CONFIG - OUTPUTS
# ==============================================================================

output "warehouse_id" {
  description = "The ID of the created Serverless SQL Warehouse"
  value       = module.databricks_workspace_config.warehouse_id
}

output "warehouse_name" {
  description = "The Name of the created Serverless SQL Warehouse"
  value       = module.databricks_workspace_config.warehouse_name
}