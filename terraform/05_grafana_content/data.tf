# ==============================================================================
# 📊 LAYER 05 — DATA SOURCES (remote state + the BI SPN secret)
# ==============================================================================

# Layer 01: Databricks workspace URL, the read-only BI SPN client id, the Secrets Manager ARN.
data "terraform_remote_state" "infra" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "dev/01-infra/terraform.tfstate"
    region = var.aws_region
  }
}

# Layer 02: the SQL Warehouse id the Infinity queries run against.
data "terraform_remote_state" "workspace" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "dev/02-workspace/terraform.tfstate"
    region = var.aws_region
  }
}

# Layer 04: the Grafana endpoint host + the ADMIN service-account token (used by the provider).
data "terraform_remote_state" "grafana" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "dev/04-grafana/terraform.tfstate"
    region = var.aws_region
  }
}

# The platform secret bundle; we read only the BI reader's OAuth client secret from it.
data "aws_secretsmanager_secret_version" "platform" {
  secret_id = data.terraform_remote_state.infra.outputs.secrets_manager_id
}

locals {
  # workspace_url already carries the scheme, e.g. https://dbc-xxxx.cloud.databricks.com
  databricks_host  = data.terraform_remote_state.infra.outputs.workspace_url
  bi_client_id     = data.terraform_remote_state.infra.outputs.bi_reader_application_id
  bi_client_secret = jsondecode(data.aws_secretsmanager_secret_version.platform.secret_string)["bi_reader_client_secret"]
  warehouse_id     = data.terraform_remote_state.workspace.outputs.warehouse_id

  metrics_table  = "${var.catalog}.${var.metadata_schema}.pipeline_metrics"
  statements_url = "${local.databricks_host}/api/2.0/sql/statements"
}
