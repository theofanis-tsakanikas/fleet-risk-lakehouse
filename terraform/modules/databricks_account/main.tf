# ==============================================================================
# 🏢 DATABRICKS ACCOUNT MODULE - IDENTITIES & METASTORE
# ==============================================================================

# --- 👤 1. SERVICE PRINCIPAL (SPN) CREATION ---
resource "databricks_service_principal" "automation_sp" {
  display_name = "databricks-${var.environment}-${var.spn_suffix}"
}

# Explicitly grant the Account Admin role to the SPN
resource "databricks_service_principal_role" "spn_metastore_admin" {
  service_principal_id = databricks_service_principal.automation_sp.id
  role                 = "account_admin"
}

# Create Secret for SPN
resource "databricks_service_principal_secret" "sp_secret" {
  service_principal_id = databricks_service_principal.automation_sp.id
}

# Store SPN Credentials in the AWS Secret created in aws-foundation
resource "aws_secretsmanager_secret_version" "spn_creds_value" {
  secret_id = var.spn_secret_arn
  secret_string = jsonencode({
    spn_client_id     = databricks_service_principal.automation_sp.application_id
    spn_client_secret = databricks_service_principal_secret.sp_secret.secret
  })
}


# --- 👥 2. ADMIN GROUP & PERMISSIONS ---
resource "databricks_group" "admins" {
  display_name = var.admin_group_name
}

# Elevate the Admin Group to Account Admins
resource "databricks_group_role" "account_admin_group" {
  group_id = databricks_group.admins.id
  role     = "account_admin"
}

# Grant the Admin Group MANAGE permission over the Service Principal
resource "databricks_access_control_rule_set" "spn_manage" {
  name = "accounts/${var.databricks_account_id}/servicePrincipals/${databricks_service_principal.automation_sp.application_id}/ruleSets/default"

  # Rule 1: Admins manage the SPN
  grant_rules {
    principals = ["groups/${databricks_group.admins.display_name}"]
    role       = "roles/servicePrincipal.manager"
  }

  # Rule 2: The SPN manages itself (Self-Manage)
  grant_rules {
    principals = ["servicePrincipals/${databricks_service_principal.automation_sp.application_id}"]
    role       = "roles/servicePrincipal.manager"
  }

  # Rule 3: Both Admins and the SPN can use the SPN (User Role)
  grant_rules {
    principals = [
      "groups/${databricks_group.admins.display_name}",
      "servicePrincipals/${databricks_service_principal.automation_sp.application_id}"
    ]
    role       = "roles/servicePrincipal.user"
  }
}


# --- ➕ 3. MEMBERSHIPS ---
# Add Users to the Admin Group
resource "databricks_group_member" "admin_members" {
  for_each  = toset(var.metastore_admins)
  group_id  = databricks_group.admins.id
  member_id = each.key
}

# Add the SPN to the Admin Group (inherits group permissions)
resource "databricks_group_member" "spn_admin_membership" {
  group_id  = databricks_group.admins.id
  member_id = databricks_service_principal.automation_sp.id
}

# Creation of Functional Groups (e.g., data-engineers, data-analysts)
resource "databricks_group" "functional_groups" {
  for_each     = toset(var.identity_groups)
  display_name = each.value
}


# --- 🧠 4. UNITY CATALOG METASTORE ---
resource "databricks_metastore" "this" {
  name          = var.metastore_name
  storage_root  = var.metastore_storage_root
  region        = var.region
  force_destroy = false

  delta_sharing_organization_name                   = var.delta_sharing_name
  delta_sharing_scope                               = "INTERNAL_AND_EXTERNAL"
  delta_sharing_recipient_token_lifetime_in_seconds = var.delta_sharing_token_lifetime

  owner = var.admin_group_name
}

# Linking the AWS IAM Role with the Metastore (Data Access)
resource "databricks_metastore_data_access" "this" {
  metastore_id = databricks_metastore.this.id
  name         = "metastore-data-access"
  is_default   = true

  aws_iam_role {
    role_arn = var.metastore_iam_role_arn # Passed from aws-iam module
  }
}