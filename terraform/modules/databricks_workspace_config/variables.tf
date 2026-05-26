# ==============================================================================
# 📊 DATABRICKS WORKSPACE CONFIG - VARIABLES
# ==============================================================================

variable "environment" {
  description = "The deployment environment (dev, staging, prod)"
  type        = string
}


# --- 🔑 Governance Variables ---
variable "metastore_id" {
  description = "The Unity Catalog Metastore ID"
  type        = string
}

variable "admin_group_name" {
  description = "The name of the admin group to grant metastore privileges"
  type        = string
}


# --- ⚡ Warehouse Compute Variables ---
variable "warehouse_prefix" {
  description = "Prefix name for the SQL warehouse"
  type        = string
}

variable "warehouse_size" {
  description = "Size of the warehouse (e.g., 2X-Small, X-Small, Small)"
  type        = string
  default     = "2X-Small"
}

variable "max_num_clusters" {
  description = "Maximum number of clusters for auto-scaling"
  type        = number
  default     = 2
}

variable "auto_stop_mins" {
  description = "Minutes of inactivity before stopping the warehouse"
  type        = number
  default     = 10
}


# --- 👥 Access Variables ---
variable "warehouse_access_groups" {
  description = "List of groups that should have usage access to the warehouse"
  type        = list(string)
}

variable "warehouse_permission_level" {
  description = "Permission level for groups (CAN_USE, CAN_MANAGE)"
  type        = string
  default     = "CAN_USE"
}