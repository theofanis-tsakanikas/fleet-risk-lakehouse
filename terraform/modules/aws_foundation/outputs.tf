# ==============================================================================
# 📦 AWS FOUNDATION MODULE - OUTPUTS
# ==============================================================================

# --- 📂 1. Data Lake Bucket Outputs ---
output "data_bucket_id" {
  description = "The name/ID of the Data Lake S3 bucket"
  value       = aws_s3_bucket.data_bucket.id
}

output "data_bucket_arn" {
  description = "The ARN of the Data Lake S3 bucket for IAM policies"
  value       = aws_s3_bucket.data_bucket.arn
}


# --- 📂 2. Metastore Bucket Outputs ---
output "metastore_bucket_id" {
  description = "The name/ID of the Metastore Root S3 bucket"
  value       = aws_s3_bucket.metastore_bucket.id
}

output "metastore_bucket_arn" {
  description = "The ARN of the Metastore Root S3 bucket for IAM policies"
  value       = aws_s3_bucket.metastore_bucket.arn
}


# --- 🔑 3. Secrets Manager Outputs ---
output "secrets_manager_arn" {
  description = "The ARN of the Secrets Manager for IAM policies"
  value       = aws_secretsmanager_secret.platform_secrets.arn
}

output "secrets_manager_id" {
  description = "The ID of the Secrets Manager for writing secret versions"
  value       = aws_secretsmanager_secret.platform_secrets.id
}