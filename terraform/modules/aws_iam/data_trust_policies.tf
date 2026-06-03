# ==============================================================================
# 🛡️ AWS IAM MODULE - DATABRICKS UNITY CATALOG ROLE & POLICIES
# ==============================================================================

# --- 📜 1. TRUST POLICY DOCUMENT ---
data "aws_iam_policy_document" "trust_policy" {

  # --- STATEMENT 1: ALLOW DATABRICKS TO ASSUME THIS ROLE ---
  statement {
    sid     = "DatabricksUCAssume"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type = "AWS"
      # Using Databricks Root Account for stability instead of a specific role
      identifiers = ["arn:aws:iam::414351767826:root"]
    }

    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      # Security lock using the External ID provided by Databricks
      values = [var.external_id]
    }
  }

  # --- STATEMENT 2: ALLOW THE ROLE TO SELF-ASSUME ---
  statement {
    sid     = "UCRoleSelfAssume"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type = "AWS"
      # Trusting our own AWS Account Root allows any entity within it (including this role) to assume itself
      identifiers = ["arn:aws:iam::${var.aws_account_id}:root"]
    }
  }
}