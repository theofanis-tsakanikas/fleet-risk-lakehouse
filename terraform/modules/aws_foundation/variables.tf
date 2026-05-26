# ==============================================================================
# 📦 AWS FOUNDATION MODULE - VARIABLES
# ==============================================================================

variable "project_name" {
  description = "The name of the project or platform (used for resource naming prefixes)"
  type        = string
}

variable "environment" {
  description = "The deployment environment (e.g., dev, staging, prod)"
  type        = string
}

variable "data_bucket_name" {
  description = "The globally unique name for the Data Lake S3 bucket"
  type        = string
}

variable "metastore_bucket_name" {
  description = "The globally unique name for the Unity Catalog Metastore S3 bucket"
  type        = string
}