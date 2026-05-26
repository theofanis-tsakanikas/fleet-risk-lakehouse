# --- 1. REMOTE STATE FROM INFRA ---
# We fetch the workspace_url and s3 bucket details dynamically from the infra layer
data "terraform_remote_state" "infra" {
  backend = "s3"

  config = {
    bucket = "generic-terraform-state-eu-central-1"
    key    = "dev/01-infra/terraform.tfstate"
    region = "eu-central-1"
  }
}

# --- 2. DATABRICKS WORKSPACE PROVIDER ---
provider "databricks" {
  alias         = "workspace"
  host          = data.terraform_remote_state.infra.outputs.workspace_url
  client_id     = var.spn_client_id
  client_secret = var.spn_client_secret
}

# --- 3. REUSABLE UNITY CATALOG MODULE ---
module "databricks_unity_catalog" {
  source = "../modules/databricks_unity_catalog"

  # We pass the necessary variables to the Unity Catalog module
  external_locations               = var.external_locations
  catalogs                         = var.catalogs
  datalake_storage_credential_name = var.datalake_storage_credential_name
  datalake_role_arn                = data.terraform_remote_state.infra.outputs.datalake_role_arn
  data_bucket_id                   = data.terraform_remote_state.infra.outputs.data_bucket_id

  # We pass the workspace provider to the child module
  providers = {
    databricks = databricks.workspace
  }
}