output "external_location_ids" {
  description = "IDs of the created external locations"
  value       = module.databricks_unity_catalog.external_location_ids
}

output "catalog_ids" {
  description = "IDs of the created catalogs"
  value       = module.databricks_unity_catalog.catalog_ids
}

output "schema_ids" {
  description = "IDs of the created schemas"
  value       = module.databricks_unity_catalog.schema_ids
}

output "volume_ids" {
  description = "IDs of the created volumes"
  value       = module.databricks_unity_catalog.volume_ids
}

