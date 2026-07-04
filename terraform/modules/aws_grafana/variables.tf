# ==============================================================================
# 📊 AMAZON MANAGED GRAFANA MODULE - VARIABLES
# ==============================================================================

variable "environment" {
  description = "The deployment environment (e.g. dev, prod)"
  type        = string
}

variable "workspace_name" {
  description = "The name of the Amazon Managed Grafana workspace"
  type        = string
}

variable "admin_user_id" {
  description = "The IAM Identity Center user id to grant Grafana ADMIN (for login + setup)"
  type        = string
}
