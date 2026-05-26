# ==============================================================================
# 🛡️ AWS IAM MODULE - OUTPUTS
# ==============================================================================

# --- 🔓 DATALAKE ROLE OUTPUTS (For Bronze, Silver, Gold Access) ---
output "datalake_role_arn" {
  description = "The ARN of the IAM role for Databricks Data Lake access"
  value       = aws_iam_role.datalake_role.arn
}

output "datalake_role_name" {
  description = "The name of the IAM role for Databricks Data Lake access"
  value       = aws_iam_role.datalake_role.name
}


# --- 🔐 METASTORE ROLE OUTPUTS (For Unity Catalog Metadata System) ---
output "metastore_role_arn" {
  description = "The ARN of the IAM role for Databricks Metastore root access"
  value       = aws_iam_role.metastore_role.arn
}

output "metastore_role_name" {
  description = "The name of the IAM role for Databricks Metastore root access"
  value       = aws_iam_role.metastore_role.name
}