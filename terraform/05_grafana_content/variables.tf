# ==============================================================================
# 📊 LAYER 05 — VARIABLES
# ==============================================================================

variable "aws_region" {
  description = "AWS region (state bucket + Secrets Manager)"
  type        = string
  default     = "eu-central-1"
}

variable "state_bucket" {
  description = "S3 bucket holding the Terraform remote state for all layers"
  type        = string
  default     = "fleet-risk-lakehouse-tfstate-eu-central-1"
}

variable "catalog" {
  description = "Unity Catalog catalog holding the Gold + metadata schemas"
  type        = string
  default     = "fleet_dev"
}

variable "metadata_schema" {
  description = "Schema holding the pipeline_metrics observability fact"
  type        = string
  default     = "metadata"
}
