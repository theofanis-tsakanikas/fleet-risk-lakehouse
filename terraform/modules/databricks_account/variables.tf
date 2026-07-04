# ==============================================================================
# 🏢 DATABRICKS ACCOUNT MODULE - VARIABLES
# ==============================================================================

variable "environment" {
  description = "The deployment environment (e.g., dev, staging, prod)"
  type        = string
}

variable "region" {
  description = "The AWS region where the metastore root bucket is located"
  type        = string
}

# --- 👤 Service Principal (SPN) Variables ---
variable "spn_suffix" {
  description = "Suffix for the Service Principal display name (e.g., github-actions)"
  type        = string
}

variable "spn_secret_arn" {
  description = "The AWS Secrets Manager Secret ARN to store the SPN client ID and secret"
  type        = string
}


# --- 👥 Groups & Users Variables ---
variable "databricks_account_id" {
  description = "The Databricks Account ID"
  type        = string
}

variable "admin_group_name" {
  description = "The display name of the main admin group"
  type        = string
}

variable "metastore_admins" {
  description = "List of user emails or user IDs to add to the Admin group"
  type        = list(string)
}

variable "identity_groups" {
  description = "List of functional groups to create (e.g., data-engineers, data-analysts)"
  type        = list(string)
}

variable "mask_privileged_group" {
  description = "Account group whose members see unmasked biometrics/location (ADR-007). Must already exist; the project SPN is added to it automatically."
  type        = string
  default     = "fleet_safety_officers"
}


# --- 🧠 Unity Catalog Metastore Variables ---
variable "metastore_name" {
  description = "The name of the Unity Catalog Metastore"
  type        = string
}

variable "metastore_storage_root" {
  description = "The S3 path for the metastore root storage (e.g., s3://metastore-bucket-name)"
  type        = string
}

variable "metastore_iam_role_arn" {
  description = "The ARN of the AWS IAM role for the metastore data access"
  type        = string
}


# --- 🌍 Delta Sharing Variables ---
variable "delta_sharing_name" {
  description = "The organization name used for Delta Sharing"
  type        = string
}

variable "delta_sharing_token_lifetime" {
  description = "Lifetime of recipient tokens in seconds (e.g., 2592000 for 30 days)"
  type        = number
  default     = 2592000 # 30 days default
}