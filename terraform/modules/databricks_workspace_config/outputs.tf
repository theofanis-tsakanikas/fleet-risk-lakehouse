# ==============================================================================
# 📊 DATABRICKS WORKSPACE CONFIG - OUTPUTS
# ==============================================================================

output "warehouse_id" {
  description = "The ID of the created Serverless SQL Warehouse"
  value       = databricks_sql_endpoint.serverless_starter.id
}

output "warehouse_name" {
  description = "The Name of the created Serverless SQL Warehouse"
  value       = databricks_sql_endpoint.serverless_starter.name
}