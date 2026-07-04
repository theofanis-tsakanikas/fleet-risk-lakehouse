# ==============================================================================
# 📊 AMAZON MANAGED GRAFANA MODULE - OUTPUTS
# ==============================================================================

output "grafana_workspace_id" {
  description = "The Amazon Managed Grafana workspace id"
  value       = aws_grafana_workspace.this.id
}

output "grafana_endpoint" {
  description = "The Grafana workspace endpoint (login here via IAM Identity Center)"
  value       = "https://${aws_grafana_workspace.this.endpoint}"
}

output "grafana_version" {
  description = "The Grafana version running in the workspace"
  value       = aws_grafana_workspace.this.grafana_version
}

output "grafana_endpoint_host" {
  description = "The Grafana workspace endpoint host (no scheme) — for the Grafana provider url"
  value       = aws_grafana_workspace.this.endpoint
}

output "service_account_token" {
  description = "Grafana service-account token (ADMIN) — used by layer 05's Grafana provider"
  value       = aws_grafana_workspace_service_account_token.tf.key
  sensitive   = true
}
