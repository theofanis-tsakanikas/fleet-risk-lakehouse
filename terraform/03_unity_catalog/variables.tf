# ==============================================================================
# 🔑 1. AUTHENTICATION VARIABLES (From Secrets)
# ==============================================================================

variable "spn_client_id" {
  description = "The Service Principal Client ID for Databricks authentication"
  type        = string
  sensitive   = true
  # Injected by terraform.sh from Secrets Manager for apply. Defaults to empty so a no-op
  # destroy of already-empty state still passes when the secret is unavailable (e.g. mid-teardown).
  default = ""
}

variable "spn_client_secret" {
  description = "The Service Principal Client Secret for Databricks authentication"
  type        = string
  sensitive   = true
  default     = ""
}

# ==============================================================================
# 🌍 2. DYNAMIC CONFIGURATION (Defaults based on your Architecture)
# ==============================================================================

variable "datalake_storage_credential_name" {
  description = "The name of the Unity Catalog Storage Credential"
  type        = string
  default     = "dev_datalake_creds"
}

variable "external_locations" {
  description = "Map of external locations to create in Unity Catalog"
  type = map(object({
    path    = string
    comment = string
    grants  = map(list(string))
  }))
  default = {
    "primary_dev_lake" = {
      path    = "unity-catalog"
      comment = "Primary storage root for Unity Catalog managed tables"
      grants = {
        "data_engineers"   = ["READ_FILES", "WRITE_FILES", "CREATE_EXTERNAL_TABLE"]
        "metastore_admins" = ["ALL_PRIVILEGES"]
      }
    },
    "landing_zone_lake" = {
      path    = "landing-zone"
      comment = "External location for raw landing zone data"
      grants = {
        "data_engineers"   = ["READ_FILES", "WRITE_FILES", "CREATE_EXTERNAL_TABLE"]
        "metastore_admins" = ["ALL_PRIVILEGES"]
      }
    }
  }
}

variable "catalogs" {
  description = "Hierarchical map of catalogs, schemas, volumes, and their grants"
  type = map(object({
    comment               = string
    external_location_key = string
    grants                = map(list(string))

    schemas = map(object({
      comment = string
      grants  = map(list(string))

      volumes = map(object({
        volume_type           = string
        external_location_key = optional(string)
        path                  = optional(string)
        comment               = string
        grants                = map(list(string))
      }))
    }))
  }))
  default = {
    # --- CATALOG 1: VEHICLE TRACKERS ---
    "trackers_dev" = {
      comment               = "Vehicle Trackers Development Catalog"
      external_location_key = "primary_dev_lake"
      grants = {
        "data_engineers"   = ["USE_CATALOG", "CREATE_SCHEMA"]
        "data_analysts"    = ["USE_CATALOG"]
        "metastore_admins" = ["ALL_PRIVILEGES"]
      }
      schemas = {
        "metadata" = {
          comment = "Technical Metadata layer - Checkpoints and Logs"
          grants  = { "data_engineers" = ["USE_SCHEMA", "CREATE_VOLUME", "CREATE_TABLE"], "metastore_admins" = ["ALL_PRIVILEGES"] }
          volumes = {
            "checkpoints" = {
              volume_type = "MANAGED"
              comment     = "Structured Streaming checkpoints for Trackers"
              grants      = { "data_engineers" = ["READ_VOLUME", "WRITE_VOLUME"], "metastore_admins" = ["ALL_PRIVILEGES"] }
            }
          }
        }
        "bronze" = {
          comment = "Bronze layer - Raw Tracker Ingestion"
          grants  = { "data_engineers" = ["USE_SCHEMA", "CREATE_TABLE", "CREATE_VOLUME"], "data_analysts" = ["USE_SCHEMA"], "metastore_admins" = ["ALL_PRIVILEGES"] }
          volumes = {
            "raw_files" = {
              volume_type           = "EXTERNAL"
              external_location_key = "landing_zone_lake"
              path                  = "trackers"
              comment               = "Browse raw tracker CSVs directly from S3"
              grants                = { "data_engineers" = ["READ_VOLUME", "WRITE_VOLUME"], "data_analysts" = ["READ_VOLUME"], "metastore_admins" = ["ALL_PRIVILEGES"] }
            }
          }
        }
        "silver" = {
          comment = "Silver layer - Cleansed Trackers"
          grants  = { "data_engineers" = ["USE_SCHEMA", "CREATE_TABLE"], "data_analysts" = ["USE_SCHEMA", "SELECT"], "metastore_admins" = ["ALL_PRIVILEGES"] }
          volumes = {}
        }
      }
    }

    # --- CATALOG 2: SMARTWATCHES & WEARABLES ---
    "wearables_dev" = {
      comment               = "Smartwatches and Fitness Wearables Development Catalog"
      external_location_key = "primary_dev_lake"
      grants = {
        "data_engineers"   = ["USE_CATALOG", "CREATE_SCHEMA"]
        "data_analysts"    = ["USE_CATALOG"]
        "metastore_admins" = ["ALL_PRIVILEGES"]
      }
      schemas = {
        "metadata" = {
          comment = "Technical Metadata layer - Checkpoints and Logs"
          grants  = { "data_engineers" = ["USE_SCHEMA", "CREATE_VOLUME", "CREATE_TABLE"], "metastore_admins" = ["ALL_PRIVILEGES"] }
          volumes = {
            "checkpoints" = {
              volume_type = "MANAGED"
              comment     = "Structured Streaming checkpoints for Wearables"
              grants      = { "data_engineers" = ["READ_VOLUME", "WRITE_VOLUME"], "metastore_admins" = ["ALL_PRIVILEGES"] }
            }
          }
        }
        "bronze" = {
          comment = "Bronze layer - Raw Wearables Ingestion"
          grants  = { "data_engineers" = ["USE_SCHEMA", "CREATE_TABLE", "CREATE_VOLUME"], "data_analysts" = ["USE_SCHEMA"], "metastore_admins" = ["ALL_PRIVILEGES"] }
          volumes = {
            "raw_files" = {
              volume_type           = "EXTERNAL"
              external_location_key = "landing_zone_lake"
              path                  = "watches"
              comment               = "Browse raw smartwatch JSONs directly from S3"
              grants                = { "data_engineers" = ["READ_VOLUME", "WRITE_VOLUME"], "data_analysts" = ["READ_VOLUME"], "metastore_admins" = ["ALL_PRIVILEGES"] }
            }
          }
        }
        "silver" = {
          comment = "Silver layer - Cleansed Wearables"
          grants  = { "data_engineers" = ["USE_SCHEMA", "CREATE_TABLE"], "data_analysts" = ["USE_SCHEMA", "SELECT"], "metastore_admins" = ["ALL_PRIVILEGES"] }
          volumes = {}
        }
      }
    }

    # --- CATALOG 3: FLEET ANALYTICS ---
    "fleet_dev" = {
      comment               = "Cross-Domain Fleet Analytics and Gold Reporting"
      external_location_key = "primary_dev_lake"
      grants = {
        "data_engineers"   = ["USE_CATALOG", "CREATE_SCHEMA"]
        "data_analysts"    = ["USE_CATALOG", "SELECT"]
        "metastore_admins" = ["ALL_PRIVILEGES"]
      }
      schemas = {
        "operations" = {
          comment = "Gold layer - Enriched Fleet Status and Safety Alerts"
          grants  = { "data_engineers" = ["USE_SCHEMA", "CREATE_TABLE"], "data_analysts" = ["USE_SCHEMA", "SELECT"], "metastore_admins" = ["ALL_PRIVILEGES"] }
          volumes = {}
        }
        "metadata" = {
          comment = "Checkpoints for Gold Layer processing + the pipeline_metrics observability fact"
          # data_analysts get USE_SCHEMA + SELECT so the read-only BI SPN (Grafana/Streamlit) can
          # read fleet_dev.metadata.pipeline_metrics. The schema holds only that operational fact
          # table (no Art. 9 biometrics); the checkpoint *volume* stays engineer-only (separate
          # READ_VOLUME securable), so analysts see the metrics table but not the checkpoints.
          grants = { "data_engineers" = ["USE_SCHEMA", "CREATE_VOLUME"], "data_analysts" = ["USE_SCHEMA", "SELECT"], "metastore_admins" = ["ALL_PRIVILEGES"] }
          volumes = {
            "checkpoints" = {
              volume_type = "MANAGED"
              comment     = "Gold layer streaming checkpoints"
              grants      = { "data_engineers" = ["READ_VOLUME", "WRITE_VOLUME"], "metastore_admins" = ["ALL_PRIVILEGES"] }
            }
          }
        }
      }
    }
  }
}