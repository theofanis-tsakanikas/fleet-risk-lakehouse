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
