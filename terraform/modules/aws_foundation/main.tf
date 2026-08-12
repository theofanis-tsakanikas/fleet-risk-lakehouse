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

# Versioning is the recovery story for the landing zone: Auto Loader reads these raw
# batches once, so an object deleted or overwritten by mistake is otherwise gone, and
# the Bronze table cannot be rebuilt from source. Non-current versions expire after 30
# days so the protection does not become an unbounded bill.
resource "aws_s3_bucket_versioning" "data_bucket" {
  bucket = aws_s3_bucket.data_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw_lifecycle" {
  bucket = aws_s3_bucket.data_bucket.id

  # Versioning must be configured before lifecycle rules that reference versions.
  depends_on = [aws_s3_bucket_versioning.data_bucket]

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

  rule {
    id     = "expire_noncurrent_versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
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

# The metastore root holds every managed Delta table. Delta's own transaction log
# gives time travel *within* a table; it does not survive an object being deleted
# underneath it, which is what this covers.
resource "aws_s3_bucket_versioning" "metastore_bucket" {
  bucket = aws_s3_bucket.metastore_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "metastore_bucket" {
  bucket = aws_s3_bucket.metastore_bucket.id

  depends_on = [aws_s3_bucket_versioning.metastore_bucket]

  rule {
    id     = "expire_noncurrent_versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}


# ==============================================================================
# 🔑 AWS SECRETS MANAGER (ENTERPRISE READY)
# ==============================================================================

resource "aws_secretsmanager_secret" "platform_secrets" {
  name        = "fleet-risk-lakehouse-${var.environment}-secrets"
  description = "Central secrets manager for the Cloud Data Platform"

  # In dev, delete immediately on destroy instead of AWS's default 30-day recovery window —
  # otherwise a destroy leaves the secret "scheduled for deletion" and the next apply fails to
  # recreate it ("a secret with this name is already scheduled for deletion"), which breaks the
  # deploy/destroy cycle this project is driven by.
  #
  # In prod that convenience is a hazard: an accidental destroy would take the SPN credentials
  # with it, unrecoverably. There, keep AWS's 30-day window — a prod rebuild is rare enough to
  # afford waiting, or to force with `aws secretsmanager delete-secret --force-delete-without-recovery`.
  recovery_window_in_days = var.environment == "prod" ? 30 : 0

  tags = {
    Name        = "${var.project_name}-secrets"
    Environment = var.environment
  }
}