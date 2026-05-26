data "terraform_remote_state" "infra" {
  backend = "s3"

  config = {
    bucket = "generic-terraform-state-eu-central-1"
    key    = "dev/01-infra/terraform.tfstate"
    region = "eu-central-1"
  }
}

provider "databricks" {
  alias         = "workspace"
  host          = data.terraform_remote_state.infra.outputs.workspace_url
  account_id    = var.databricks_account_id
  client_id     = var.spn_client_id
  client_secret = var.spn_client_secret
}

provider "time" {}

# ==============================================================================

# --- 📊 Module 1: Databricks Workspace Config (Governance & SQL Compute) ---
module "databricks_workspace_config" {
  source = "../modules/databricks_workspace_config"

  environment                = var.environment
  metastore_id               = data.terraform_remote_state.infra.outputs.metastore_id
  admin_group_name           = var.admin_group_name
  warehouse_prefix           = var.warehouse_prefix
  warehouse_size             = var.warehouse_size
  max_num_clusters           = var.max_num_clusters
  auto_stop_mins             = var.auto_stop_mins
  warehouse_access_groups    = var.warehouse_access_groups
  warehouse_permission_level = var.warehouse_permission_level

  # We use the Workspace Provider here to configure inside the Workspace
  providers = {
    databricks = databricks.workspace
  }
}
