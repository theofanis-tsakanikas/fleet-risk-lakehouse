variable "aws_region" {
  description = "AWS region for the Grafana workspace"
  type        = string
  default     = "eu-central-1"
}

variable "environment" {
  description = "Deployment environment (e.g. dev, prod)"
  type        = string
  default     = "dev"
}

variable "workspace_name" {
  description = "Amazon Managed Grafana workspace name"
  type        = string
  default     = "fleet-risk-grafana"
}

variable "grafana_admin_user_id" {
  description = "IAM Identity Center user id to grant Grafana ADMIN. Provided via TF_VAR_grafana_admin_user_id (not committed)."
  type        = string
}
