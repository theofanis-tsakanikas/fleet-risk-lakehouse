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
# Target-aware: the override file must land under the target being deployed,
# otherwise a `prod` deploy would silently miss the spn_id override.
BUNDLE_TARGET="${BUNDLE_TARGET:-dev}"
BUNDLE_OVERRIDE_PATH=".databricks/bundle/$BUNDLE_TARGET"
BUNDLE_JOB_NAME="${BUNDLE_JOB_NAME:-simulated_sensors_job}"

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
    echo "📋 Validating Bundle (target: $BUNDLE_TARGET)..."
    databricks bundle validate -t "$BUNDLE_TARGET"
    ;;
  deploy)
    echo "🚀 Deploying Bundle (target: $BUNDLE_TARGET)..."
    databricks bundle deploy -t "$BUNDLE_TARGET" --auto-approve
    ;;
  run)
    echo "🏃 Running Job: $BUNDLE_JOB_NAME (target: $BUNDLE_TARGET)..."
    databricks bundle run -t "$BUNDLE_TARGET" "$BUNDLE_JOB_NAME"
    ;;
  *)
    echo "❌ Usage: ./bundle.sh <validate|deploy|run>   (env: BUNDLE_TARGET=dev|prod, BUNDLE_JOB_NAME=...)"
    exit 1
    ;;
esac