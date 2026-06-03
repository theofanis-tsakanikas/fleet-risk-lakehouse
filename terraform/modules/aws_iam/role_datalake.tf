# --- 🏗️ IAM ROLE RESOURCE ---
resource "aws_iam_role" "datalake_role" {
  name                  = var.datalake_role_name
  assume_role_policy    = data.aws_iam_policy_document.trust_policy.json
  force_detach_policies = true

  tags = {
    Name        = var.datalake_role_name
    Environment = var.environment
  }
}


# --- 📂 S3 STORAGE ACCESS POLICY (FOR 2 BUCKETS) ---
data "aws_iam_policy_document" "read_write_s3_access" {
  statement {
    sid    = "AllowBucketLevelActions"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
      "s3:ListBucketMultipartUploads"
    ]

    resources = [
      var.data_bucket_arn,
    ]
  }

  statement {
    sid    = "AllowObjectLevelActions"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListMultipartUploadParts",
      "s3:AbortMultipartUpload"
    ]

    resources = [
      "${var.data_bucket_arn}/*",
    ]
  }

  statement {
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::${var.aws_account_id}:role/${var.datalake_role_name}"]
  }
}

resource "aws_iam_policy" "databricks_policy" {
  name        = "${var.project_name}-${var.environment}-s3-access-policy"
  description = "Allows Databricks to read and write to the data and metastore buckets"
  policy      = data.aws_iam_policy_document.read_write_s3_access.json
}


# --- 🔑 SECRETS MANAGER ACCESS POLICY ---
data "aws_iam_policy_document" "secrets_access" {
  statement {
    sid    = "AllowSecretsManagerRead"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]
    resources = [var.secrets_manager_arn]
  }
}

resource "aws_iam_policy" "secrets_policy" {
  name        = "${var.project_name}-${var.environment}-secrets-access-policy"
  description = "Allows Databricks to read platform secrets"
  policy      = data.aws_iam_policy_document.secrets_access.json
}


# --- 📡 MANAGED FILE EVENTS POLICY (Autoloader applied to Data Lake) ✅ ---
data "aws_iam_policy_document" "managed_file_events" {
  statement {
    sid    = "ManagedFileEventsSetupStatement"
    effect = "Allow"
    actions = [
      "s3:GetBucketNotification",
      "s3:PutBucketNotification",
      "sns:ListSubscriptionsByTopic",
      "sns:GetTopicAttributes",
      "sns:SetTopicAttributes",
      "sns:CreateTopic",
      "sns:TagResource",
      "sns:Publish",
      "sns:Subscribe",
      "sqs:CreateQueue",
      "sqs:DeleteMessage",
      "sqs:ReceiveMessage",
      "sqs:SendMessage",
      "sqs:GetQueueUrl",
      "sqs:GetQueueAttributes",
      "sqs:SetQueueAttributes",
      "sqs:TagQueue",
      "sqs:ChangeMessageVisibility",
      "sqs:PurgeQueue"
    ]
    resources = [
      var.data_bucket_arn,
      "arn:aws:sqs:*:*:csms-*",
      "arn:aws:sns:*:*:csms-*"
    ]
  }

  statement {
    sid    = "ManagedFileEventsListStatement"
    effect = "Allow"
    actions = [
      "sqs:ListQueues",
      "sqs:ListQueueTags",
      "sns:ListTopics"
    ]
    resources = [
      "arn:aws:sqs:*:*:csms-*",
      "arn:aws:sns:*:*:csms-*"
    ]
  }

  statement {
    sid    = "ManagedFileEventsTeardownStatement"
    effect = "Allow"
    actions = [
      "sns:Unsubscribe",
      "sns:DeleteTopic",
      "sqs:DeleteQueue"
    ]
    resources = [
      "arn:aws:sqs:*:*:csms-*",
      "arn:aws:sns:*:*:csms-*"
    ]
  }
}

resource "aws_iam_policy" "managed_file_events" {
  name        = "${var.project_name}-${var.environment}-autoloader-policy"
  description = "Policy for Databricks Managed File Events (Autoloader)"
  policy      = data.aws_iam_policy_document.managed_file_events.json
}


# --- 🔗 6. MAIN ROLE ATTACHMENTS ---
resource "aws_iam_role_policy_attachment" "attach_s3_policy" {
  role       = aws_iam_role.datalake_role.name
  policy_arn = aws_iam_policy.databricks_policy.arn
}

resource "aws_iam_role_policy_attachment" "attach_secrets_policy" {
  role       = aws_iam_role.datalake_role.name
  policy_arn = aws_iam_policy.secrets_policy.arn
}

resource "aws_iam_role_policy_attachment" "attach_managed_file_events_policy" {
  role       = aws_iam_role.datalake_role.name
  policy_arn = aws_iam_policy.managed_file_events.arn
}