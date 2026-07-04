output "grafana_endpoint" {
  description = "Grafana login URL (authenticate via IAM Identity Center)"
  value       = module.grafana.grafana_endpoint
}

output "grafana_workspace_id" {
  description = "The Amazon Managed Grafana workspace id"
  value       = module.grafana.grafana_workspace_id
}

output "grafana_version" {
  description = "The Grafana version running in the workspace"
  value       = module.grafana.grafana_version
}
