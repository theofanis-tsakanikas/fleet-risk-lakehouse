#!/bin/bash

# ==============================================================================
# 🚀 DATABRICKS BUNDLE AUTOMATION SCRIPT (Hybrid Mode)
# ==============================================================================

# --- ⚙️ CONFIGURATION ---
# Change these values in one place if your project structure changes
TERRAFORM_EXEC="./terraform.sh"
INFRA_MODULE="01_infra"

# Terraform Output Names
OUT_WORKSPACE_URL="workspace_url"
OUT_SPN_APP_ID="spn_application_id"

# Bundle Config
BUNDLE_OVERRIDE_PATH=".databricks/bundle/dev"
BUNDLE_JOB_NAME="fleet_monitoring_job"

# --- 1. Smart Configuration Discovery ---
# Fetch DATABRICKS_HOST if not already provided by the environment (e.g. CI/CD)
if [ -z "$DATABRICKS_HOST" ]; then
    echo "🔍 Host not found in env. Fetching from Terraform ($INFRA_MODULE)..."
    export DATABRICKS_HOST=$($TERRAFORM_EXEC $INFRA_MODULE output -raw $OUT_WORKSPACE_URL 2>/dev/null)
fi

# Fetch SPN_ID if not already provided
if [ -z "$SPN_ID" ]; then
    echo "🔍 SPN_ID not found in env. Fetching from Terraform ($INFRA_MODULE)..."
    SPN_ID=$($TERRAFORM_EXEC $INFRA_MODULE output -raw $OUT_SPN_APP_ID 2>/dev/null)
fi

# Final Validation
if [ -z "$DATABRICKS_HOST" ] || [ -z "$SPN_ID" ]; then
    echo "❌ Error: Could not resolve DATABRICKS_HOST or SPN_ID."
    echo "👉 Locally: Run '$TERRAFORM_EXEC $INFRA_MODULE apply' first."
    echo "👉 CI/CD: Ensure variables are passed in the workflow YAML."
    exit 1
fi

# --- 2. Create Local Bundle Overrides ---
mkdir -p "$BUNDLE_OVERRIDE_PATH"
echo "{\"spn_id\": \"$SPN_ID\"}" > "$BUNDLE_OVERRIDE_PATH/variable-overrides.json"

echo "✅ Environment Ready!"
echo "🌐 Host: $DATABRICKS_HOST"
echo "🆔 SPN ID: $SPN_ID"

# --- 3. Execution Logic ---
ACTION=$1

case $ACTION in
  validate)
    echo "📋 Validating Bundle..."
    databricks bundle validate
    ;;
  deploy)
    echo "🚀 Deploying Bundle..."
    databricks bundle deploy --auto-approve
    ;;
  run)
    echo "🏃 Running Job: $BUNDLE_JOB_NAME..."
    databricks bundle run "$BUNDLE_JOB_NAME"
    ;;
  *)
    echo "❌ Usage: ./bundle.sh <validate|deploy|run>"
    exit 1
    ;;
esac