# ==============================================================================
# 💻 DATABRICKS WORKSPACE MODULE - OUTPUTS
# ==============================================================================

output "workspace_id" {
  description = "The ID of the created Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_id
}

output "workspace_url" {
  description = "The URL of the created Databricks workspace"
  value       = databricks_mws_workspaces.this.workspace_url
}

output "ncc_id" {
  description = "The Network Connectivity Configuration ID"
  value       = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
}