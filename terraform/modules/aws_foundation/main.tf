# ==============================================================================
# 📦 1. S3 BUCKET FOR DATA LAKE (EXTERNAL TABLES)
# ==============================================================================

resource "aws_s3_bucket" "data_bucket" {
  bucket = var.data_bucket_name

  force_destroy = var.environment == "prod" ? false : true

  tags = {
    Name        = "${var.project_name}-data-lake"
    Environment = var.environment
    Layer       = "raw"
  }
}

resource "aws_s3_bucket_public_access_block" "data_bucket" {
  bucket                  = aws_s3_bucket.data_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_bucket" {
  bucket = aws_s3_bucket.data_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw_lifecycle" {
  bucket = aws_s3_bucket.data_bucket.id

  rule {
    id     = "cleanup_temp"
    status = "Enabled"

    filter {
      prefix = "temp/"
    }

    expiration {
      days = 7
    }
  }
}


# ==============================================================================
# 📦 2. S3 BUCKET FOR UNITY CATALOG METASTORE (MANAGED TABLES)
# ==============================================================================

resource "aws_s3_bucket" "metastore_bucket" {
  bucket = var.metastore_bucket_name

  force_destroy = var.environment == "prod" ? false : true

  tags = {
    Name        = "${var.project_name}-metastore-root"
    Environment = var.environment
    Layer       = "metastore"
  }
}

resource "aws_s3_bucket_public_access_block" "metastore_bucket" {
  bucket                  = aws_s3_bucket.metastore_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "metastore_bucket" {
  bucket = aws_s3_bucket.metastore_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}


# ==============================================================================
# 🔑 AWS SECRETS MANAGER (ENTERPRISE READY)
# ==============================================================================

resource "aws_secretsmanager_secret" "platform_secrets" {
  name        = "fleet-risk-lakehouse-${var.environment}-secrets"
  description = "Central secrets manager for the Cloud Data Platform"

  # Delete immediately on destroy instead of AWS's default 30-day recovery window — otherwise a
  # destroy leaves the secret "scheduled for deletion" and the next apply fails to recreate it
  # ("a secret with this name is already scheduled for deletion"). Fine for a dev/rebuild flow.
  recovery_window_in_days = 0

  tags = {
    Name        = "${var.project_name}-secrets"
    Environment = var.environment
  }
}