terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.37.0"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "1.117.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.13.1"
    }
  }
  backend "s3" {
    bucket  = "generic-terraform-state-eu-central-1"
    key     = "dev/01-infra/terraform.tfstate"
    region  = "eu-central-1"
    encrypt = true
  }
}



