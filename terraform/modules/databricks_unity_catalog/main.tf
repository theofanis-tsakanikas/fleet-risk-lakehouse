# --- 0. STORAGE CREDENTIAL ---
# Creates a Storage Credential in Unity Catalog that links to the AWS IAM Role created in 01_infra. 
# This allows Unity Catalog to read/write data in your S3 Data Lake.
resource "databricks_storage_credential" "datalake" {
  name = var.datalake_storage_credential_name

  aws_iam_role {
    role_arn = var.datalake_role_arn
  }
}


# --- 1. DYNAMIC EXTERNAL LOCATIONS ---
# Maps your S3 paths to Databricks Unity Catalog
resource "databricks_external_location" "this" {
  for_each        = var.external_locations
  name            = each.key
  url             = "s3://${var.data_bucket_id}/${each.value.path}/" 
  credential_name = databricks_storage_credential.datalake.name
  comment         = each.value.comment
  force_destroy   = true
}

# --- 2. DYNAMIC EXTERNAL LOCATION GRANTS ---
# Controls who can bypass Unity Catalog and read/write raw files directly from S3
locals {
  ext_location_grants = flatten([
    for loc_name, loc_data in var.external_locations : [
      for principal, privileges in loc_data.grants : {
        key       = "${loc_name}.${principal}"
        location  = loc_name
        principal = principal
        privileges = privileges
      }
    ]
  ])
}

resource "databricks_grants" "external_locations" {
  for_each          = var.external_locations
  external_location = each.key

  dynamic "grant" {
    for_each = each.value.grants
    content {
      principal  = grant.key
      privileges = grant.value
    }
  }
}

# --- 3. DYNAMIC CATALOGS ---
# Creates catalogs and dynamically links them to their corresponding External Locations
resource "databricks_catalog" "this" {
  for_each = var.catalogs
  name     = each.key
  comment  = each.value.comment

  # Dynamically appends the catalog name to the External Location URL
  storage_root = databricks_external_location.this[each.value.external_location_key].url
}

# --- 4. DYNAMIC CATALOG GRANTS ---
# Controls high-level catalog permissions (e.g., USE_CATALOG, CREATE_SCHEMA)
locals {
  catalog_grants = flatten([
    for cat_name, cat_data in var.catalogs : [
      for principal, privileges in cat_data.grants : {
        key       = "${cat_name}.${principal}"
        catalog   = cat_name
        principal = principal
        privileges = privileges
      }
    ]
  ])
}

resource "databricks_grants" "catalogs" {
  for_each = var.catalogs
  catalog  = each.key

  dynamic "grant" {
    for_each = each.value.grants
    content {
      principal  = grant.key
      privileges = grant.value
    }
  }
}

# --- 5. FLATTENING SCHEMAS FOR LOOPING ---
locals {
  schema_list = flatten([
    for cat_name, cat_data in var.catalogs : [
      for schema_name, schema_data in cat_data.schemas : {
        key          = "${cat_name}.${schema_name}"
        catalog_name = cat_name
        schema_name  = schema_name
        comment      = schema_data.comment
        volumes      = schema_data.volumes
        grants       = schema_data.grants
      }
    ]
  ])
}

# --- 6. DYNAMIC SCHEMAS ---
resource "databricks_schema" "this" {
  for_each     = { for s in local.schema_list : s.key => s }
  catalog_name = each.value.catalog_name
  name         = each.value.schema_name
  comment      = each.value.comment

  depends_on = [databricks_catalog.this]
}

# --- 7. DYNAMIC SCHEMA GRANTS ---
# Controls schema-level permissions (e.g., USE_SCHEMA, CREATE_TABLE, SELECT)
locals {
  schema_grants = flatten([
    for s in local.schema_list : [
      for principal, privileges in s.grants : {
        key       = "${s.key}.${principal}"
        schema    = "${s.catalog_name}.${s.schema_name}"
        principal = principal
        privileges = privileges
      }
    ]
  ])
}

resource "databricks_grants" "schemas" {
  for_each = { for s in local.schema_list : s.key => s }
  schema   = "${each.value.catalog_name}.${each.value.schema_name}"

  dynamic "grant" {
    for_each = each.value.grants
    content {
      principal  = grant.key
      privileges = grant.value
    }
  }

  depends_on = [databricks_schema.this]
}

# --- 8. FLATTENING VOLUMES FOR LOOPING ---
locals {
  volume_list = flatten([
    for s in local.schema_list : [
      for vol_name, vol_data in s.volumes : {
        key                   = "${s.key}.${vol_name}"
        catalog_name          = s.catalog_name
        schema_name           = s.schema_name
        volume_name           = vol_name
        volume_type           = vol_data.volume_type
        external_location_key = vol_data.external_location_key
        path                  = vol_data.path                  
        comment               = vol_data.comment
        grants                = vol_data.grants
      }
    ]
  ])
}

# --- 9. DYNAMIC VOLUMES ---
# Creates Managed or External volumes within schemas
resource "databricks_volume" "this" {
  for_each     = { for v in local.volume_list : v.key => v }
  name         = each.value.volume_name
  catalog_name = each.value.catalog_name
  schema_name  = each.value.schema_name
  volume_type  = each.value.volume_type
  comment      = each.value.comment

  # <--- FOR EXTERNAL VOLUMES --->
  storage_location = each.value.volume_type == "EXTERNAL" ? "${databricks_external_location.this[each.value.external_location_key].url}/${each.value.path}/" : null
  depends_on = [databricks_schema.this]
}

# --- 10. DYNAMIC VOLUME GRANTS ---
# Controls who can read or write raw files inside a specific Volume
locals {
  volume_grants = flatten([
    for v in local.volume_list : [
      for principal, privileges in v.grants : {
        key       = "${v.key}.${principal}"
        volume    = "${v.catalog_name}.${v.schema_name}.${v.volume_name}"
        principal = principal
        privileges = privileges
      }
    ]
  ])
}

resource "databricks_grants" "volumes" {
  for_each = { for v in local.volume_list : v.key => v }
  volume   = "${each.value.catalog_name}.${each.value.schema_name}.${each.value.volume_name}"

  dynamic "grant" {
    for_each = each.value.grants
    content {
      principal  = grant.key
      privileges = grant.value
    }
  }

  depends_on = [databricks_volume.this]
}