# ==============================================================================
# 🔑 1. PROVIDER & AUTHENTICATION VARIABLES
# ==============================================================================

variable "databricks_account_id" {
  description = "The Databricks Account ID"
  type        = string
}

variable "spn_client_id" {
  description = "The Client (Application) ID of the Service Principal used for workspace config"
  type        = string
  # Injected by terraform.sh from Secrets Manager for apply. Defaults to empty so a no-op
  # destroy of already-empty state still passes when the secret is unavailable (e.g. mid-teardown).
  default = ""
}

variable "spn_client_secret" {
  description = "The Client Secret of the Service Principal used for workspace config"
  type        = string
  sensitive   = true
  default     = ""
}

# ==============================================================================
# ⚙️ 2. ENVIRONMENT & GOVERNANCE
# ==============================================================================

variable "environment" {
  description = "The environment name (e.g., dev, prod)"
  type        = string
  default     = "dev"
}

variable "admin_group_name" {
  description = "The name of the Databricks admin group"
  type        = string
  default     = "metastore_admins"
}

# ==============================================================================
# ⚡ 3. DATABRICKS SQL WAREHOUSE CONFIGURATION
# ==============================================================================

variable "warehouse_prefix" {
  description = "Prefix for the SQL Warehouse naming"
  type        = string
  default     = "serverless_bi"
}

variable "warehouse_size" {
  description = "The size of the SQL Warehouse (e.g., 2X-Small, X-Small, Small)"
  type        = string
  default     = "2X-Small"
}

variable "max_num_clusters" {
  description = "Maximum number of clusters for the SQL Warehouse auto-scaling"
  type        = number
  default     = 2
}

variable "auto_stop_mins" {
  description = "Minutes of inactivity before the SQL Warehouse stops"
  type        = number
  default     = 10
}

variable "warehouse_access_groups" {
  description = "List of groups that should have access to the SQL Warehouse"
  type        = list(string)
  default     = ["data_engineers", "data_analysts"]
}

variable "warehouse_permission_level" {
  description = "Default permission level for the groups on the SQL Warehouse"
  type        = string
  default     = "CAN_USE"
}