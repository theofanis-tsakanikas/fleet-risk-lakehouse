#!/bin/bash

# ==============================================================================
# 🚀 RUN SCRIPT - MULTI-LAYER TERRAFORM & AUTOMATION
# ==============================================================================

# --- 📂 1. GET ARGUMENTS FIRST (Critical for silent mode) ---
MODULE=$1
ACTION=$2

if [ -z "$MODULE" ] || [ -z "$ACTION" ]; then
  echo "❌ Usage: ./terraform.sh <module> <action>"
  echo "👉 Example: ./terraform.sh 01_infra plan"
  exit 1
fi

# --- 📂 2. Load environment variables from .env ---
if [ -f .env ]; then
  # We ALWAYS export the variables so Terraform can access the backend (S3/Azure).
  # `set -a` + `source` handles quoted values, spaces and inline comments correctly
  # (the old `export $(grep ... | xargs)` silently corrupted such values).
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a

  # But we ONLY print the message if we are NOT in output mode
  if [ "$ACTION" != "output" ]; then
    echo "✅ Loading environment variables from .env..."
  fi
fi

# --- 📂 3. Navigate to the correct directory ---
TARGET_DIR="terraform/$MODULE"

if [ -d "$TARGET_DIR" ]; then
  cd "$TARGET_DIR"
  [[ "$ACTION" != "output" ]] && echo "📂 Moved to $TARGET_DIR directory!"
else
  echo "❌ Error: Directory '$TARGET_DIR' not found!"
  exit 1
fi

# --- 🔑 4. Secret Fetching Logic (For workspace AND unity_catalog modules) ---
if { [ "$MODULE" == "02_workspace" ] || [ "$MODULE" == "03_unity_catalog" ]; } && { [ "$ACTION" == "plan" ] || [ "$ACTION" == "apply" ] || [ "$ACTION" == "destroy" ]; }; then
  echo "🕵️  Fetching Service Principal credentials from infra state..."

  # The output read below needs 01_infra initialised (its S3 backend configured). During an
  # apply that is already true (01 was applied first this session), but a standalone destroy of
  # 02/03 starts from a fresh runner where 01 was never init'd — so init it quietly here. init
  # is idempotent and changes nothing; without it the credential fetch returns empty and the
  # destroy fails with "No value for required variable spn_client_id".
  terraform -chdir=../01_infra init -input=false >/dev/null 2>&1

  # Read the Secret ARN from the 01_infra state
  SECRET_ARN=$(terraform -chdir=../01_infra output -raw secrets_manager_id 2>/dev/null)
  
  if [ -z "$SECRET_ARN" ] || [[ "$SECRET_ARN" == *"No outputs"* ]]; then
    echo "⚠️  Warning: Could not fetch secret ARN from 01_infra. Make sure 01_infra apply has run!"
  else
    echo "🔑 Found Secret ARN. Fetching JSON from AWS Secrets Manager..."
    SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output text 2>/dev/null)
    
    if [ -n "$SECRET_JSON" ]; then
      # Use jq to parse the JSON and load values into memory
      export TF_VAR_spn_client_id=$(echo "$SECRET_JSON" | jq -r .spn_client_id)
      export TF_VAR_spn_client_secret=$(echo "$SECRET_JSON" | jq -r .spn_client_secret)
      echo "✅ Credentials loaded into memory successfully!"
    else
      echo "❌ Error: Failed to fetch secret values from AWS Secrets Manager."
    fi
  fi
fi

# --- ⚙️ 5. Execution Logic ---
case $ACTION in
  fmt)
    echo "🎨 Formatting Terraform files..."
    terraform fmt -recursive
    ;;
  init)
    echo "🏗️  Initializing Terraform..."
    terraform init -input=false
    ;;
  plan)
    echo "🏗️  Ensuring Terraform is initialized..."
    terraform init -input=false -backend-config=../../backend.tfvars 2>/dev/null || terraform init -input=false
    echo "📋 Running Terraform Plan..."
    terraform plan -input=false
    ;;
  apply)
    # Always init before apply so a fresh clone works without a manual step
    echo "🏗️  Initializing Terraform before apply..."
    terraform init -input=false
    echo "🚀 Running Terraform Apply..."
    terraform apply -auto-approve -input=false
    ;;
  destroy)
    echo "🏗️  Initializing Terraform before destroy..."
    terraform init -input=false
    echo "💥 Running Terraform Destroy..."
    terraform destroy -auto-approve -input=false
    ;;
  output)
    # 1. Remove $1 (module) and $2 (action) from the arguments list
    shift 2

    # Ensure the layer is initialised so `output` works on a fresh runner (e.g. the run
    # workflow, where bundle.sh reads workspace_url/spn_application_id from 01_infra without a
    # prior apply this session). Idempotent + quiet so scripted `-raw` output stays clean.
    terraform init -input=false >/dev/null 2>&1

    # 2. Check if there are any arguments left (like -raw or variable_name)
    if [ $# -eq 0 ]; then
      # No arguments provided: Show all outputs with a nice header (for the human)
      echo "🔍 Fetching all Terraform outputs for module $MODULE..."
      terraform output
    else
      # Arguments provided: Be "silent" and return only what was requested (for the script)
      terraform output "$@"
    fi
    ;;
   *)
    echo "❌ Unknown action: $ACTION"
    exit 1
    ;;
esac