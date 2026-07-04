terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.37.0"
    }
  }
  backend "s3" {
    bucket  = "fleet-risk-lakehouse-tfstate-eu-central-1"
    key     = "dev/04-grafana/terraform.tfstate"
    region  = "eu-central-1"
    encrypt = true
    # S3-native state locking (Terraform >= 1.10) — no DynamoDB table needed.
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}
