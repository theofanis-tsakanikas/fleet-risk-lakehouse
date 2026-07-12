terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.54.0"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "1.112.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.13.1"
    }
  }
  backend "s3" {
    bucket  = "fleet-risk-lakehouse-tfstate-eu-central-1"
    key     = "dev/02-workspace/terraform.tfstate"
    region  = "eu-central-1"
    encrypt = true
    # S3-native state locking (Terraform >= 1.10) — prevents concurrent applies
    # from corrupting this layer's state without needing a DynamoDB table.
    use_lockfile = true
  }
}

