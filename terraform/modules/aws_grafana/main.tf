# ==============================================================================
# 📊 AMAZON MANAGED GRAFANA — operational monitoring over the Databricks lakehouse
# ==============================================================================
# A fully-managed Grafana workspace (no server to run). It queries the Databricks SQL
# Warehouse via the Databricks data source plugin (configured in-app with the read-only BI
# SPN) to trend the `pipeline_metrics` fact — join match rate, quarantine count, risk-score
# drift (PSI), and the risk-band distribution. Login is via AWS IAM Identity Center (SSO).

# The workspace's IAM role. With account_access_type = CURRENT_ACCOUNT the API requires a role
# ARN (Terraform does not auto-create one like the console does). The Databricks source is added
# in-app via the plugin (SPN OAuth), so this role is not on that path — it just grants read
# access to AWS-native data sources (CloudWatch) for completeness, kept minimal.
data "aws_iam_policy_document" "grafana_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["grafana.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "grafana" {
  name               = "${var.workspace_name}-workspace-role"
  assume_role_policy = data.aws_iam_policy_document.grafana_assume.json
}

resource "aws_iam_role_policy_attachment" "grafana_cloudwatch" {
  role       = aws_iam_role.grafana.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess"
}

resource "aws_grafana_workspace" "this" {
  name        = var.workspace_name
  description = "Fleet Risk Lakehouse — operational monitoring over the Databricks SQL Warehouse"

  account_access_type      = "CURRENT_ACCOUNT"
  authentication_providers = ["AWS_SSO"]
  permission_type          = "CUSTOMER_MANAGED"
  role_arn                 = aws_iam_role.grafana.arn

  tags = {
    Project     = "fleet-risk-lakehouse"
    Environment = var.environment
  }
}

# Make the Identity Center user a Grafana ADMIN so they can log in, add the Databricks data
# source, and import the dashboards.
resource "aws_grafana_role_association" "admin" {
  role         = "ADMIN"
  user_ids     = [var.admin_user_id]
  workspace_id = aws_grafana_workspace.this.id
}
