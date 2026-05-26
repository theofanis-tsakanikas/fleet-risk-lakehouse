# ==============================================================================
# 📊 DATABRICKS WORKSPACE CONFIG - GOVERNANCE & COMPUTE
# ==============================================================================

# --- 📜 1. Metastore-Level Governance ---
# Defines which identities can create top-level Unity Catalog objects
resource "databricks_grants" "metastore_grants" {
  metastore = var.metastore_id

  grant {
    principal = var.admin_group_name
    privileges = [
      "CREATE CATALOG",            # Required for Federated and Managed Catalogs
      "CREATE EXTERNAL LOCATION",  # Required for S3 data access
      "CREATE STORAGE CREDENTIAL", # Required for identity bridging
      "CREATE CONNECTION",         # Required for Lakehouse Federation (BQ/SQL)
      "CREATE SHARE",              # Required for Provider-side Delta Sharing
      "CREATE RECIPIENT"           # Required for Recipient-side Delta Sharing
    ]
  }
}

# Delay to ensure Metastore permissions have propagated before compute creation
resource "time_sleep" "wait_for_metastore_grants" {
  depends_on      = [databricks_grants.metastore_grants]
  create_duration = "60s"
}


# --- ⚡ 2. Starter Serverless SQL Warehouse ---
# This acts as the central compute hub for BI tools and ad-hoc SQL queries
resource "databricks_sql_endpoint" "serverless_starter" {
  name             = "${var.warehouse_prefix}-${var.environment}"
  cluster_size     = var.warehouse_size
  max_num_clusters = var.max_num_clusters

  # Enable Serverless (PRO type is required for advanced federation features)
  warehouse_type            = "PRO"
  enable_serverless_compute = true

  # Shuts down quickly during inactivity to optimize costs
  auto_stop_mins = var.auto_stop_mins

  tags {
    custom_tags {
      key   = "Purpose"
      value = "General-BI"
    }
  }

  depends_on = [time_sleep.wait_for_metastore_grants]
}

# Short delay to allow the Warehouse API state to stabilize
resource "time_sleep" "wait_for_warehouse" {
  depends_on      = [databricks_sql_endpoint.serverless_starter]
  create_duration = "30s"
}


# --- 🔑 3. Usage Permissions for Multiple Groups ---
# Manages who can actually run queries on the provisioned Warehouse
resource "databricks_permissions" "warehouse_usage" {
  sql_endpoint_id = databricks_sql_endpoint.serverless_starter.id

  # Dynamic block to apply access levels to all groups in the input list
  dynamic "access_control" {
    for_each = toset(var.warehouse_access_groups)
    content {
      group_name       = access_control.value
      permission_level = var.warehouse_permission_level
    }
  }

  depends_on = [time_sleep.wait_for_warehouse]
}