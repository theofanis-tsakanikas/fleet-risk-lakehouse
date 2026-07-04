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

output "grafana_endpoint_host" {
  description = "The Grafana endpoint host (no scheme) — consumed by layer 05's Grafana provider"
  value       = module.grafana.grafana_endpoint_host
}

output "service_account_token" {
  description = "Grafana ADMIN service-account token — consumed by layer 05 via remote state"
  value       = module.grafana.service_account_token
  sensitive   = true
}
