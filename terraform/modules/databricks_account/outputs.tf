# ==============================================================================
# 🏢 DATABRICKS ACCOUNT MODULE - OUTPUTS
# ==============================================================================

# --- 🧠 1. Unity Catalog Metastore Outputs ---
output "metastore_id" {
  description = "The ID of the created Unity Catalog Metastore"
  value       = databricks_metastore.this.id
}

output "metastore_name" {
  description = "The display name of the created Unity Catalog Metastore"
  value       = databricks_metastore.this.name
}


# --- 👤 2. Service Principal (SPN) Outputs ---
output "spn_application_id" {
  description = "The Application (Client) ID of the Service Principal"
  value       = databricks_service_principal.automation_sp.application_id
}

output "spn_id" {
  description = "The internal Databricks ID of the Service Principal"
  value       = databricks_service_principal.automation_sp.id
}

output "bi_reader_application_id" {
  description = "The Application (Client) ID of the read-only BI (Grafana/Streamlit) Service Principal"
  value       = databricks_service_principal.bi_reader.application_id
}


# --- 👥 3. Groups Outputs ---
output "admin_group_id" {
  description = "The internal Databricks ID of the Admin group"
  value       = databricks_group.admins.id
}

output "functional_group_ids" {
  description = "A map of functional group display names to their Databricks IDs"
  value       = { for k, v in databricks_group.functional_groups : k => v.id }
}