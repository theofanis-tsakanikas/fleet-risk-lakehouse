# ------------------------------------------------------------------------------
# 🏗️ ROLE A: METASTORE SYSTEM ROLE (Only for Unity Catalog Metadata)
# ------------------------------------------------------------------------------
resource "aws_iam_role" "metastore_role" {
  name                  = var.metastore_role_name
  assume_role_policy    = data.aws_iam_policy_document.trust_policy.json
  force_detach_policies = true
}

data "aws_iam_policy_document" "metastore_s3_access" {
  statement {
    sid     = "MetastoreBucketListing"
    effect  = "Allow"
    actions = ["s3:ListBucket", "s3:GetBucketLocation", "s3:ListBucketMultipartUploads"]
    resources = [var.metastore_bucket_arn]
  }

  statement {
    sid     = "MetastoreObjectActions"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListMultipartUploadParts", "s3:AbortMultipartUpload"]
    resources = ["${var.metastore_bucket_arn}/*"]
  }
}

resource "aws_iam_policy" "metastore_s3_policy" {
  name   = "${var.project_name}-${var.environment}-metastore-s3-policy"
  policy = data.aws_iam_policy_document.metastore_s3_access.json
}

resource "aws_iam_role_policy_attachment" "attach_metastore_s3" {
  role       = aws_iam_role.metastore_role.name
  policy_arn = aws_iam_policy.metastore_s3_policy.arn
}