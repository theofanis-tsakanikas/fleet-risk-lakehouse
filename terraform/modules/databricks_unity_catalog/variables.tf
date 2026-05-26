# --- DATALAKE STORAGE CREDENTIAL ---
variable "datalake_storage_credential_name" {
  description = "The name of the Unity Catalog Storage Credential for the Data Lake"
  type        = string
}

# --- DATALAKE ROLE ARN ---
variable "datalake_role_arn" {
  description = "The AWS ARN for the Data Lake IAM Role"
  type        = string
}

variable "data_bucket_id" {
  description = "The ID or name of the S3 bucket where telemetry data is stored"
  type        = string
}

# --- EXTERNAL LOCATIONS VARIABLE ---
variable "external_locations" {
  description = "Map of external locations to create in Unity Catalog"
  type = map(object({
    path             = string
    comment         = string
    grants          = map(list(string)) # e.g., "data_engineers" = ["READ_FILES", "WRITE_FILES"]
  }))
  default = {}
}

# --- CATALOGS, SCHEMAS & VOLUMES VARIABLE ---
variable "catalogs" {
  description = "Hierarchical map of catalogs, schemas, volumes, and their grants"
  type = map(object({
    comment               = string
    external_location_key = string # Link to the external_locations map key
    grants                = map(list(string))
    
    schemas = map(object({
      comment = string
      grants  = map(list(string))
      
      volumes = map(object({
        volume_type = string # "MANAGED" or "EXTERNAL"
        external_location_key = optional(string)
        path        = optional(string)
        comment     = string
        grants      = map(list(string))
      }))
    }))
  }))
  default = {}
}