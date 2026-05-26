# ==============================================================================
# 💻 DATABRICKS WORKSPACE MODULE - CREATION & NETWORK
# ==============================================================================

# --- 🏗️ 1. Workspace Creation ---
resource "databricks_mws_workspaces" "this" {
  account_id     = var.databricks_account_id
  aws_region     = var.region
  workspace_name = "${var.workspace_name}-${var.environment}"
  
  pricing_tier   = var.workspace_pricing_tier 
  compute_mode   = "SERVERLESS"
}

# --- 🔗 2. Metastore Assignment ---
resource "databricks_metastore_assignment" "this" {
  metastore_id = var.metastore_id
  workspace_id = databricks_mws_workspaces.this.workspace_id
}

# --- 👥 3. Permission Assignments ---
resource "databricks_mws_permission_assignment" "workspace_admin_assignment" {
  workspace_id = databricks_mws_workspaces.this.workspace_id
  principal_id = var.admin_group_id
  permissions  = ["ADMIN"]

  depends_on = [databricks_metastore_assignment.this]
}

resource "databricks_mws_permission_assignment" "all_groups_assignment" {
  for_each     = var.functional_group_ids
  workspace_id = databricks_mws_workspaces.this.workspace_id
  principal_id = each.value
  permissions  = ["USER"] 
  depends_on   = [databricks_metastore_assignment.this]
}

resource "time_sleep" "wait_for_identity_sync" {
  depends_on = [
    databricks_mws_permission_assignment.workspace_admin_assignment, 
    databricks_mws_permission_assignment.all_groups_assignment
  ]
  create_duration = "60s"
}

# --- 📡 4. Network Connectivity Config (NCC for Serverless) ---
resource "databricks_mws_network_connectivity_config" "ncc" {
  account_id = var.databricks_account_id
  name       = "ncc-${var.workspace_name}-${var.environment}"
  region     = var.region
}

resource "time_sleep" "wait_30_seconds" {
  depends_on = [databricks_mws_network_connectivity_config.ncc]
  destroy_duration = "30s"
}

resource "databricks_mws_ncc_binding" "this" {
  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  workspace_id                   = databricks_mws_workspaces.this.workspace_id
  depends_on                     = [time_sleep.wait_30_seconds]
}