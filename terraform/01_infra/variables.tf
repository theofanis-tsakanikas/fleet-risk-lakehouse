# ==============================================================================
# 🌍 1. GENERAL & ENVIRONMENT SETTINGS
# ==============================================================================

variable "project_name" {
  description = "A short prefix for all resources (e.g., dp-aws, acme-plt)"
  type        = string
  default     = "dp-aws"
}

variable "environment" {
  description = "The environment name (e.g., dev, qa, prod)"
  type        = string
  default     = "dev"
}

# ==============================================================================
# ☁️ 2. AWS VARIABLES
# ==============================================================================

variable "aws_region" {
  description = "The AWS Region to deploy resources"
  type        = string
  default     = "eu-central-1"
}

variable "aws_account_id" {
  description = "Your 12-digit AWS Account ID (set via TF_VAR_aws_account_id; placeholder default)"
  type        = string
  default     = "123456789012"
}

variable "data_bucket_name" {
  description = "The globally unique name for the Data Lake bucket"
  type        = string
  default     = "fleet-risk-lakehouse-datalake-eu-central-1"
}

variable "metastore_bucket_name" {
  description = "The globally unique name for the Unity Catalog metastore bucket"
  type        = string
  default     = "fleet-risk-lakehouse-metastore-eu-central-1"
}

variable "datalake_role_name" {
  description = "The name of the IAM role to create for Databricks Unity Catalog access"
  type        = string
  default     = "databricks-datalake-role"
}

variable "metastore_role_name" {
  description = "The name of the IAM role to create for Databricks Unity Catalog metastore access"
  type        = string
  default     = "databricks-metastore-role"
}

# ==============================================================================
# 🏢 3. DATABRICKS ACCOUNT VARIABLES
# ==============================================================================

variable "databricks_account_id" {
  description = "The Databricks Account ID found in the Account Console"
  type        = string
}

variable "databricks_client_id" {
  description = "The Client ID of the Account Admin Service Principal used for deployment"
  type        = string
}

variable "databricks_client_secret" {
  description = "The Client Secret of the Account Admin Service Principal used for deployment"
  type        = string
  sensitive   = true
}

variable "spn_suffix" {
  description = "A suffix for the automated Service Principal name"
  type        = string
  default     = "cicd-automation"
}

# ==============================================================================
# 🧠 4. IDENTITY & GOVERNANCE VARIABLES (UNITY CATALOG)
# ==============================================================================

variable "admin_group_name" {
  description = "The display name of the main admin group in Databricks"
  type        = string
  default     = "metastore_admins"
}

variable "metastore_admins" {
  description = "List of user IDs (Account Console) to add to the admin group"
  type        = list(string)
  # This list is not just the human admins. The metastore sets `owner = admin_group_name`, so the
  # bootstrap SPN Terraform authenticates as loses its metastore privileges the instant ownership
  # transfers to that group — the root data access created straight after then fails with "does
  # not have CREATE EXTERNAL LOCATION". Its numeric id therefore has to be in here, and it has to
  # be the *current* one: rotate the SPN and this list must follow, or the apply breaks. A dead id
  # is just as fatal (the member cannot be read back), so replace it, never append.
  default = ["79066160746664", "73933173578533"]
}

variable "identity_groups" {
  description = "List of functional groups to create"
  type        = list(string)
  default     = ["data_engineers", "data_analysts", "business_users"]
}

variable "mask_privileged_group" {
  description = "Account group whose members see unmasked biometrics/location (ADR-007). Must exist before apply; the project SPN is added to it automatically."
  type        = string
  default     = "fleet_safety_officers"
}

variable "metastore_name" {
  description = "The name of the Unity Catalog Metastore"
  type        = string
  default     = "primary-metastore-eu-central-1"
}

variable "delta_sharing_name" {
  description = "The name of the Delta Sharing organization"
  type        = string
  default     = "company-delta-share"
}

variable "delta_sharing_token_lifetime" {
  description = "The lifetime in seconds for recipient tokens in Delta Sharing"
  type        = number
  default     = 2592000 # 30 days
}

# ==============================================================================
# 💻 5. WORKSPACE VARIABLES
# ==============================================================================

variable "workspace_name" {
  description = "The name of the Databricks Workspace to create"
  type        = string
  default     = "analytics-workspace"
}

variable "workspace_pricing_tier" {
  description = "Pricing tier for the workspace (PREMIUM or ENTERPRISE)"
  type        = string
  default     = "ENTERPRISE"
}