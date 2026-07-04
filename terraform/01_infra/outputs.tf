# ==============================================================================
# 📦 AWS FOUNDATION MODULE - OUTPUTS
# ==============================================================================

# --- 📂 1. Data Lake Bucket Outputs ---
output "data_bucket_id" {
  description = "The name/ID of the Data Lake S3 bucket"
  value       = module.aws_foundation.data_bucket_id
}

output "data_bucket_arn" {
  description = "The ARN of the Data Lake S3 bucket for IAM policies"
  value       = module.aws_foundation.data_bucket_arn
}


# --- 📂 2. Metastore Bucket Outputs ---
output "metastore_bucket_id" {
  description = "The name/ID of the Metastore Root S3 bucket"
  value       = module.aws_foundation.metastore_bucket_id
}

output "metastore_bucket_arn" {
  description = "The ARN of the Metastore Root S3 bucket for IAM policies"
  value       = module.aws_foundation.metastore_bucket_arn
}


# --- 🔑 3. Secrets Manager Outputs ---
output "secrets_manager_arn" {
  description = "The ARN of the Secrets Manager for IAM policies"
  value       = module.aws_foundation.secrets_manager_arn
}

output "secrets_manager_id" {
  description = "The ID of the Secrets Manager for writing secret versions"
  value       = module.aws_foundation.secrets_manager_id
}

# ==============================================================================
# 🛡️ AWS IAM MODULE - OUTPUTS
# ==============================================================================

# --- 🔓 DATALAKE ROLE OUTPUTS (For Bronze, Silver, Gold Access) ---
output "datalake_role_arn" {
  description = "The ARN of the IAM role for Databricks Data Lake access"
  value       = module.aws_iam.datalake_role_arn
}

output "datalake_role_name" {
  description = "The name of the IAM role for Databricks Data Lake access"
  value       = module.aws_iam.datalake_role_name
}


# --- 🔐 METASTORE ROLE OUTPUTS (For Unity Catalog Metadata System) ---
output "metastore_role_arn" {
  description = "The ARN of the IAM role for Databricks Metastore root access"
  value       = module.aws_iam.metastore_role_arn
}

output "metastore_role_name" {
  description = "The name of the IAM role for Databricks Metastore root access"
  value       = module.aws_iam.metastore_role_name
}

# ==============================================================================
# 🏢 DATABRICKS ACCOUNT MODULE - OUTPUTS
# ==============================================================================

# --- 🧠 1. Unity Catalog Metastore Outputs ---
output "metastore_id" {
  description = "The ID of the created Unity Catalog Metastore"
  value       = module.databricks_account.metastore_id
}

output "metastore_name" {
  description = "The display name of the created Unity Catalog Metastore"
  value       = module.databricks_account.metastore_name
}


# --- 👤 2. Service Principal (SPN) Outputs ---
output "spn_application_id" {
  description = "The Application (Client) ID of the Service Principal"
  value       = module.databricks_account.spn_application_id
}

output "spn_id" {
  description = "The internal Databricks ID of the Service Principal"
  value       = module.databricks_account.spn_id
}

output "bi_reader_application_id" {
  description = "Client ID of the read-only BI (Grafana/Streamlit) Service Principal; its secret is in Secrets Manager (bi_reader_client_secret)"
  value       = module.databricks_account.bi_reader_application_id
}


# --- 👥 3. Groups Outputs ---
output "admin_group_id" {
  description = "The internal Databricks ID of the Admin group"
  value       = module.databricks_account.admin_group_id
}

output "functional_group_ids" {
  description = "A map of functional group display names to their Databricks IDs"
  value       = module.databricks_account.functional_group_ids
}

# ==============================================================================
# 💻 DATABRICKS WORKSPACE MODULE - OUTPUTS
# ==============================================================================

output "workspace_id" {
  description = "The ID of the created Databricks workspace"
  value       = module.databricks_workspace.workspace_id
}

output "workspace_url" {
  description = "The URL of the created Databricks workspace"
  value       = module.databricks_workspace.workspace_url
}

output "ncc_id" {
  description = "The Network Connectivity Configuration ID"
  value       = module.databricks_workspace.ncc_id
}

