# Security

## Scope

This repository is a **portfolio reference implementation** of a lakehouse that processes
**special-category personal data under GDPR Art. 9** — heart rate and stress. That classification is
the reason this file is longer than the usual template: the controls below are the point of the
project, not an afterthought to it.

**No real physiological data is ever processed.** Biometrics are simulated throughout — including in
the real-data replay, where only the *telemetry* is genuine (real GPS traces, speeds and
hard-braking events from the Vehicle Energy Dataset) and the heart rate and stress are generated
conditioned on those real events. The Art. 9 controls exist because the *shape* of the data is
special-category and the platform is built as if it were real.

Read this alongside [What this does not do](README.md#what-this-does-not-do) in the README. Nothing
is claimed here that the code does not do.

## Reporting a vulnerability

Open a [GitHub issue](https://github.com/theofanis-tsakanikas/fleet-risk-lakehouse/issues) for
anything non-sensitive. For something that should not be public, email the address on the
[GitHub profile](https://github.com/theofanis-tsakanikas) with `SECURITY` in the subject. There is
no bug bounty and no SLA; this is a personal project and a best-effort response is what it can
honestly promise.

Only `main` is supported. There are no maintained release branches.

---

## What is hardened

### Special-category data — enforced by the platform, not by a policy

This is the control that matters most, so it is stated precisely.

`heart_rate` and `stress_score` are classified as **GDPR Art. 9 special-category data** in
[`src/fleet_governance/classification.py`](src/fleet_governance/classification.py), and the Unity
Catalog **column masks** are *derived from that classification* rather than written beside it. The
mask predicate is a single group-membership check,
`is_account_group_member('fleet_safety_officers')`, so the same query returns different data
depending on who runs it — biometrics `NULL` and location coarsened for everyone outside the group.

Three properties are worth separating out:

- **It applies to all four Gold surfaces** — live status, alerts, quarantine and aggregates. The
  aggregate table is included deliberately, because aggregation does not de-identify
  ([ADR-007](docs/adr/ADR-007-column-masking.md)).
- **There is no application layer to bypass.** The mask is bound to the column in Unity Catalog;
  querying the table directly, from any client, gets the same treatment.
- **A CI test fails if any Gold column is left unclassified.** You cannot add a column and forget to
  decide what it is.

The generated [GDPR Art. 30 processing record](docs/governance/) and the risk model card are
rendered from the same classification and the same model object, and CI's `--check` fails the build
if the committed documents drift from the code.

### Nothing special-category leaves the platform

Outbound Slack and PagerDuty notifications are built by projecting each alert onto
`NOTIFY_FIELDS` — an **allowlist** of operational and derived fields in
[`src/fleet_alerting/alerts.py`](src/fleet_alerting/alerts.py) — and a test asserts it.

The direction matters: a payload built by *removing* the sensitive fields leaks the first time
someone adds a column. Built by *listing* the permitted ones, it cannot.

### Identity and access

- **Keyless CI.** Every cloud workflow authenticates to AWS via **GitHub OIDC**; no long-lived AWS
  key is stored in the repository.
- **Every cloud-mutating workflow targets the `production` GitHub Environment**, and the deploy is
  `workflow_dispatch`-only — a merge to `main` cannot provision infrastructure. The destroy
  additionally requires a typed confirmation and an explicit cumulative scope.
- **Workflow permissions are minimal** — `contents: read` everywhere, `id-token: write` only where
  OIDC is actually used, `pull-requests: write` only on the workflow that posts plan comments.
- **The BI principal is deliberately unprivileged.** Grafana queries as `grafana-bi-reader-dev`, a
  `data_analysts` member with `SELECT` on two schemas — **not** an account admin, and **not** in
  `fleet_safety_officers`. So the dashboards show risk scores, drift and coarse location while raw
  biometrics stay masked, by construction rather than by dashboard configuration.
- **The project SPN's credentials are never typed by hand.** `terraform.sh` reads them from AWS
  Secrets Manager after layer 01 and injects them as `TF_VAR_*` for layers 02 and 03.
- **Fork pull requests are refused** by a guard on the plan workflow, so a fork cannot obtain a
  token or produce misleading empty plans.

### Storage

Both S3 buckets — the data lake and the Unity Catalog metastore root — carry a full public-access
block (`block_public_acls`, `block_public_policy`, `ignore_public_acls`, `restrict_public_buckets`),
`AES256` server-side encryption, and **versioning**, with non-current versions expiring after 30
days and incomplete multipart uploads aborted after 7. `force_destroy` is `false` in prod, and the
Secrets Manager recovery window is environment-gated — 30 days in prod, immediate in dev where the
deploy/destroy cycle needs it.

`tests/test_infra_offline.py` asserts each of those controls on the module source, so removing one
is a failing test rather than a silent one-line change.

### Terraform state

Five layers, each with its own isolated S3 backend key. A failed or partial destroy of layer 03
cannot corrupt layer 01's state, and concurrent plans on different layers do not contend
([ADR-001](docs/adr/ADR-001-terraform-layered-state.md)).

### Secrets in the repository

`.env`, `*.tfstate`, `*.tfvars`, `.terraform/` and `app/.streamlit/secrets.toml` are gitignored, and
[`gitleaks`](.github/workflows/gitleaks.yml) scans the **full git history** (`fetch-depth: 0`) on
every push and pull request. A real `app/.streamlit/secrets.toml` exists on the
development machine and is untracked — the ignore rule covering it is committed, so it is protected
by rule rather than by luck.

---

## Known limitations

Each is stated with the control a real deployment would use instead.

### 1. The deployer role's trust policy is not in this repository

The GitHub OIDC provider and the `AWS_DEPLOY_ROLE_ARN` role are a **manual one-time prerequisite**.
Nothing here declares them, so nothing here can verify **which** branches, environments or
repositories are permitted to assume that role. If it was created with the common
`repo:<owner>/<repo>:*` subject condition, any workflow on any branch can assume it.

*A deployment would* declare the provider and the role in a bootstrap Terraform layer with the
subject condition pinned to the exact subjects its workflows present (`pull_request`,
`ref:refs/heads/main`, `environment:production`) — and would keep that policy under review with the
rest of the code. **Verify yours by hand until then.**

### 2. Unity Catalog masks protect the query path, not the storage path

This is the most important caveat on the Art. 9 claim, and it is a property of the architecture
rather than a bug. Column masks are enforced by Unity Catalog when a principal *queries a table*.
The underlying Delta files live in the metastore S3 bucket, and a principal holding the storage
credential's IAM role could read that Parquet directly, unmasked, bypassing Unity Catalog entirely.

*A deployment would* treat the storage-credential role as a privileged identity in its own right —
minimal trust policy, access logging, alerting on direct `s3:GetObject` against the metastore
prefix — and would not hand it to humans. The masks are the control for analysts; they are not a
control against someone with the bucket role.

### 3. The pipeline's own service principal sees unmasked biometrics

Layer 01 adds the project SPN to `fleet_safety_officers` automatically, so the pipeline's own
biometric null-rate metrics read real values rather than masked ones. This is deliberate — a
data-quality metric computed on masked data is meaningless — but it means the identity that runs
every job is a privileged one.

*A deployment would* separate the compute identity from the reader identity, or compute those
metrics inside the masked boundary and export only the aggregate.

### 4. Local runs use IAM admin access keys

CI is keyless, but a local `terraform apply` authenticates with an IAM admin user's access keys in
`.env`, and the Databricks Account-Admin SPN is a manual prerequisite with broad account rights.

*A deployment would* use short-lived credentials (SSO / `aws sso login`, or an assumed role) for
humans, and would scope the bootstrap identity down once the account exists.

### 5. There is no required-reviewer gate on the `production` environment

Every cloud workflow targets that environment, which is the right structure — but the approval gate
that would make it meaningful requires GitHub Pro or above on a private repository, and is not
configured. Today the environment provides scoping, not a second pair of eyes.

### 6. The Grafana service-account token is long-lived and manually rotated

Layer 05 authenticates with a **30-day** service-account token emitted by layer 04. Rotation means
re-applying 04 and then 05, by hand. There is no automatic rotation and no alert before expiry.

### 7. The Streamlit app has no authentication, and promotes every secret to the environment

[`app/`](app/) is a demo surface. Anyone who can reach the port reads whatever the configured
principal can read — which is exactly why the principal it is given matters, and why live mode
should point at the unprivileged BI service principal rather than an admin token.

It also copies **every** entry of `st.secrets` into `os.environ` at start-up, so whatever else that
file happens to hold becomes visible to any subprocess. Promoting only the five keys the data layer
reads would narrow that, and is the right change in a codebase under active development — it is not
applied here because the app is deployed and working, and the fix would silently stop promoting a
key someone's local secrets file relies on.

### 8. No dependency or container vulnerability scanning

`gitleaks` covers secrets, and Dependabot **security** updates are enabled — but nothing produces an
SBOM or scans for CVEs, and routine version updates are deliberately switched off
(`open-pull-requests-limit: 0`) because this is a pinned reference implementation rather than a
library under maintenance.

### 9. Teardown leaves account-level objects behind

The Databricks API refuses to delete a metastore from CI even with `force_destroy`, so the destroy
is a documented **two-pass** operation with a manual deletion in the middle. Until the second pass
completes, account-level groups and the metastore survive — which is an availability and hygiene
problem rather than an exposure, but it is why a re-deploy can fail with
`Group with name data_engineers already exists`.

---

## Pre-publish checklist

Before making the repository public, and after any change to the infrastructure or governance
layers:

- [ ] `gitleaks` is green over the **full history**, not just the latest diff
- [ ] `git ls-files` lists no `.tfstate`, `.tfvars`, `.env`, `secrets.toml` or key material
- [ ] No real AWS account id, workspace URL or ARN appears in a committed screenshot
- [ ] `make check` passes — including `govern-check`, so the generated Art. 30 record matches the code
- [ ] Every Gold column is still classified (the suite enforces this; confirm it ran)
- [ ] Both buckets still declare public-access block, encryption and versioning
- [ ] The deployer role's trust policy has been inspected by hand — see limitation 1
- [ ] `fleet_safety_officers` contains only the principals that genuinely need unmasked biometrics
