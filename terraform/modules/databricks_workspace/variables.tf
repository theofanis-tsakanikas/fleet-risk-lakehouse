# ==============================================================================
# 💻 DATABRICKS WORKSPACE MODULE - VARIABLES
# ==============================================================================

variable "environment" {
  description = "The deployment environment (e.g., dev, staging, prod)"
  type        = string
}

variable "region" {
  description = "The AWS region where the workspace will be deployed"
  type        = string
}

variable "databricks_account_id" {
  description = "The Databricks Account ID"
  type        = string
}


# --- 🏢 Workspace Specific Variables ---
variable "workspace_name" {
  description = "The base name of the workspace"
  type        = string
}

variable "workspace_pricing_tier" {
  description = "The pricing tier of the workspace (e.g., PREMIUM, ENTERPRISE)"
  type        = string
  default     = "PREMIUM"
}


# --- 🔗 Metastore & Identity Variables ---
variable "metastore_id" {
  description = "The ID of the Unity Catalog Metastore to assign to this workspace"
  type        = string
}

variable "admin_group_id" {
  description = "The Databricks ID of the admin group to grant ADMIN permissions in the workspace"
  type        = string
}

variable "functional_group_ids" {
  description = "A map of functional group names to their Databricks IDs to grant USER permissions"
  type        = map(string)
}