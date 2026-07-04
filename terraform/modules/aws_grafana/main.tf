# ==============================================================================
# 📊 AMAZON MANAGED GRAFANA — operational monitoring over the Databricks lakehouse
# ==============================================================================
# A fully-managed Grafana workspace (no server to run). It queries the Databricks SQL
# Warehouse via the free, OSS **Infinity** datasource (which POSTs to the Databricks SQL
# Statement Execution REST API using the read-only BI SPN over OAuth2) to trend the
# `pipeline_metrics` fact — join match rate, quarantine count, risk-score drift (PSI), and the
# risk-band distribution. The Enterprise Databricks plugin is deliberately avoided (it costs an
# extra $45/user/mo on AMG). Login is via AWS IAM Identity Center (SSO); the datasource +
# dashboards are provisioned as code from layer 05 via the Grafana provider, authenticated with
# the service-account token this module emits. See docs/adr/ADR-010-grafana-infinity-datasource.md.

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

  # Required so we can install the community (OSS) Infinity plugin into the workspace via the
  # Grafana HTTP API — without it AMG rejects plugin installs. On AMG this is set through the
  # workspace `configuration` JSON (there is no top-level attribute). In-place update.
  configuration = jsonencode({
    plugins         = { pluginAdminEnabled = true }
    unifiedAlerting = { enabled = false } # match the AMG default so the config shows no perpetual diff
  })

  tags = {
    Project     = "fleet-risk-lakehouse"
    Environment = var.environment
  }
}

# Make the Identity Center user a Grafana ADMIN so they can log in and see the dashboards.
resource "aws_grafana_role_association" "admin" {
  role         = "ADMIN"
  user_ids     = [var.admin_user_id]
  workspace_id = aws_grafana_workspace.this.id
}

# ------------------------------------------------------------------------------
# 🔑 Service account + token — the credential the Grafana Terraform provider (layer 05) and the
# plugin-install step below authenticate with. Replaces deprecated workspace API keys (AMG 9+).
# The token is shown only once (its `key`); it is surfaced as a sensitive module output, kept in
# the encrypted layer-04 state, and read by layer 05 via terraform_remote_state.
# ------------------------------------------------------------------------------
resource "aws_grafana_workspace_service_account" "tf" {
  name         = "terraform-automation"
  grafana_role = "ADMIN"
  workspace_id = aws_grafana_workspace.this.id
}

resource "aws_grafana_workspace_service_account_token" "tf" {
  name               = "terraform-token"
  service_account_id = aws_grafana_workspace_service_account.tf.service_account_id
  seconds_to_live    = 2592000 # 30 days — the AMG maximum. Re-apply rotates it (new token forces replace).
  workspace_id       = aws_grafana_workspace.this.id
}

# ------------------------------------------------------------------------------
# 🔌 Install the OSS Infinity datasource plugin. AMG has no Terraform-native plugin resource
# (the grafana_plugin* resources are Grafana-Cloud only), so we call the workspace's Grafana
# HTTP API with the service-account token. Idempotent: the install endpoint returns a
# "plugin already installed" 4xx on re-runs, which we treat as success.
# ------------------------------------------------------------------------------
resource "null_resource" "install_infinity" {
  triggers = {
    workspace = aws_grafana_workspace.this.id
    version   = var.infinity_plugin_version
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      body=$(test -n "${var.infinity_plugin_version}" && echo '{"version":"${var.infinity_plugin_version}"}' || echo '{}')
      code=$(curl -s -o /tmp/infinity_install.out -w '%%{http_code}' -X POST \
        -H "Authorization: Bearer ${aws_grafana_workspace_service_account_token.tf.key}" \
        -H "Content-Type: application/json" \
        "https://${aws_grafana_workspace.this.endpoint}/api/plugins/yesoreyeram-infinity-datasource/install" \
        -d "$body")
      echo "install HTTP $code: $(cat /tmp/infinity_install.out)"
      # 200/201 = installed; 409/400 "already installed" = fine. Fail only on auth/5xx.
      case "$code" in
        2*|409) exit 0 ;;
        4*) grep -qi "already" /tmp/infinity_install.out && exit 0 || { echo "plugin install failed"; exit 1; } ;;
        *) echo "plugin install failed"; exit 1 ;;
      esac
    EOT
  }

  depends_on = [aws_grafana_workspace_service_account_token.tf]
}
