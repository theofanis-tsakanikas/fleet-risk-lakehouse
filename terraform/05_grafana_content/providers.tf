# ==============================================================================
# 📊 LAYER 05 — GRAFANA CONTENT (Infinity datasource + dashboards, as code)
# ==============================================================================
# Provisions the Grafana *content* (a Databricks-over-Infinity datasource + the pipeline
# observability dashboard) on top of the workspace from layer 04. It is a separate layer on
# purpose: the Grafana provider authenticates with the service-account token that layer 04
# creates, and a provider cannot be configured from a resource created in the same apply
# ("provider bootstrap" problem). Reading the token from layer 04's remote state makes it a
# known value at plan time here, so a single `apply` works cleanly.
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.37.0"
    }
    grafana = {
      source  = "grafana/grafana"
      version = "~> 3.18"
    }
  }
  backend "s3" {
    bucket       = "fleet-risk-lakehouse-tfstate-eu-central-1"
    key          = "dev/05-grafana-content/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}

provider "grafana" {
  url  = "https://${data.terraform_remote_state.grafana.outputs.grafana_endpoint_host}"
  auth = data.terraform_remote_state.grafana.outputs.service_account_token
}
