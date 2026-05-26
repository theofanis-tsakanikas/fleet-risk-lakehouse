# ==============================================================================
# 🛡️ AWS IAM MODULE - VARIABLES
# ==============================================================================

variable "project_name" {
  description = "The name of the project or platform (used for resource naming prefixes)"
  type        = string
}

variable "environment" {
  description = "The deployment environment (e.g., dev, staging, prod)"
  type        = string
}

variable "aws_account_id" {
  description = "The AWS Account ID where resources are deployed"
  type        = string
}

variable "datalake_role_name" {
  description = "The name of the IAM role to create for Databricks Unity Catalog access"
  type        = string
}

variable "metastore_role_name" {
  description = "The name of the IAM role to create for Databricks Unity Catalog metastore access"
  type        = string
}

variable "external_id" {
  description = "The External ID for the trust relationship (dummy '0000' for first apply, real ID for second apply)"
  type        = string
}

variable "data_bucket_arn" {
  description = "The ARN of the Data Lake S3 bucket to grant access to"
  type        = string
}

variable "metastore_bucket_arn" {
  description = "The ARN of the Metastore Root S3 bucket to grant access to"
  type        = string
}

variable "secrets_manager_arn" {
  description = "The ARN of the Secrets Manager to grant access to"
  type        = string
}
