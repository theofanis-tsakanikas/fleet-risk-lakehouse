output "external_location_ids" {
  description = "Map of created external location IDs"
  value       = { for k, v in databricks_external_location.this : k => v.id }
}

output "catalog_ids" {
  description = "Map of created catalog IDs"
  value       = { for k, v in databricks_catalog.this : k => v.id }
}

output "schema_ids" {
  description = "Map of created schema IDs"
  value       = { for k, v in databricks_schema.this : k => v.id }
}

output "volume_ids" {
  description = "Map of created volume IDs"
  value       = { for k, v in databricks_volume.this : k => v.id }
}