provider "aws" {
  region = var.aws_region
}


provider "databricks" {
  alias         = "account"
  host          = "https://accounts.cloud.databricks.com"
  account_id    = var.databricks_account_id
  client_id     = var.databricks_client_id
  client_secret = var.databricks_client_secret
}

provider "time" {}

# ==============================================================================
# 🚀 ROOT MODULE - CLOUD DATA PLATFORM ORCHESTRATION
# ==============================================================================

# --- 📦 Module 1: AWS Foundation (Buckets & Secrets) ---
module "aws_foundation" {
  source = "../modules/aws_foundation"

  project_name          = var.project_name
  environment           = var.environment
  data_bucket_name      = var.data_bucket_name
  metastore_bucket_name = var.metastore_bucket_name
}


# --- 🛡️ Module 2: AWS IAM (Roles & Policies) ---
module "aws_iam" {
  source = "../modules/aws_iam"

  project_name        = var.project_name
  environment         = var.environment
  aws_account_id      = var.aws_account_id
  datalake_role_name  = var.datalake_role_name
  metastore_role_name = var.metastore_role_name
  external_id         = var.databricks_account_id

  data_bucket_arn      = module.aws_foundation.data_bucket_arn
  metastore_bucket_arn = module.aws_foundation.metastore_bucket_arn
  secrets_manager_arn  = module.aws_foundation.secrets_manager_arn
}


# --- 🏢 Module 3: Databricks Account (Identities & Metastore) ---
module "databricks_account" {
  source = "../modules/databricks_account"

  environment                  = var.environment
  region                       = var.aws_region
  databricks_account_id        = var.databricks_account_id
  spn_suffix                   = var.spn_suffix
  spn_secret_arn               = module.aws_foundation.secrets_manager_id
  admin_group_name             = var.admin_group_name
  metastore_admins             = var.metastore_admins
  identity_groups              = var.identity_groups
  mask_privileged_group        = var.mask_privileged_group
  metastore_name               = var.metastore_name
  metastore_storage_root       = "s3://${module.aws_foundation.metastore_bucket_id}"
  metastore_iam_role_arn       = module.aws_iam.metastore_role_arn
  delta_sharing_name           = var.delta_sharing_name
  delta_sharing_token_lifetime = var.delta_sharing_token_lifetime

  # We use the Account Provider here
  providers = {
    databricks = databricks.account
  }
}


# --- 💻 Module 4: Databricks Workspace (Creation & NCC) ---
module "databricks_workspace" {
  source = "../modules/databricks_workspace"

  environment            = var.environment
  region                 = var.aws_region
  databricks_account_id  = var.databricks_account_id
  workspace_name         = var.workspace_name
  workspace_pricing_tier = var.workspace_pricing_tier
  metastore_id           = module.databricks_account.metastore_id
  admin_group_id         = module.databricks_account.admin_group_id
  functional_group_ids   = module.databricks_account.functional_group_ids

  # We use the Account Provider here to create the Workspace
  providers = {
    databricks = databricks.account
  }
}

