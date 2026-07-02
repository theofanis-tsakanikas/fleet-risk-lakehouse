# ==============================================================================
# Fleet Risk Lakehouse — task runner.
#
# A thin, discoverable front door over the project's tooling. The heavy logic
# (multi-layer Terraform ordering + SPN secret injection, DABs host/SPN
# resolution) stays in the shell scripts — terraform.sh / bundle.sh / setup.sh —
# which the GitHub Actions workflows also call. This Makefile just gives them a
# clean, uniform interface and bundles the quality gates the CI runs.
#
# Run `make` (or `make help`) to list every target.
# ==============================================================================

# Use the project venv by default; override with `make test PYTHON=python3`.
# The venv's `python` symlink works even though its `pip` shebang is stale —
# always go through `$(PYTHON) -m pip`, never `.venv/bin/pip`.
PYTHON ?= .venv/bin/python

# ruff format / lint scope — kept identical to .github/workflows/ci.yml so
# `make fmt-check` and the CI gate never disagree.
FMT_SCOPE := src/fleet_transforms src/fleet_governance src/replay src/mock_generator/generators.py tests

.DEFAULT_GOAL := help

# ---- guards -----------------------------------------------------------------
# `make plan LAYER=01_infra` — fail clearly if a required variable is missing.
guard-%:
	@test -n "$($*)" || { echo "❌ Missing required variable: $* (e.g. make $(MAKECMDGOALS) $*=01_infra)"; exit 1; }

# ==============================================================================
# Help
# ==============================================================================
.PHONY: help
help: ## Show this help
	@echo "Fleet Risk Lakehouse — make targets:"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Terraform targets take LAYER=<01_infra|02_workspace|03_unity_catalog>."

# ==============================================================================
# Local dev & quality gates (no cloud credentials needed)
# ==============================================================================
.PHONY: setup
setup: ## Bootstrap local env (.venv + .env) via setup.sh
	./setup.sh

.PHONY: test
test: ## Run the local test suite (pytest: pure-Python + local PySpark)
	$(PYTHON) -m pytest -ra

.PHONY: lint
lint: ## Lint with ruff (src, notebooks, tests)
	$(PYTHON) -m ruff check src notebooks tests

.PHONY: fmt-check
fmt-check: ## Check formatting with ruff (CI-scoped, read-only)
	$(PYTHON) -m ruff format --check $(FMT_SCOPE)

.PHONY: fmt
fmt: ## Apply ruff formatting (CI-scoped)
	$(PYTHON) -m ruff format $(FMT_SCOPE)

.PHONY: govern-docs
govern-docs: ## Regenerate the governance docs (risk model card + GDPR Art. 30 record)
	PYTHONPATH=src $(PYTHON) -m fleet_governance.generate

.PHONY: govern-check
govern-check: ## Fail if the committed governance docs are stale
	PYTHONPATH=src $(PYTHON) -m fleet_governance.generate --check

.PHONY: check
check: lint fmt-check test govern-check ## Run every gate the CI runs (lint + format + tests + govern)
	@echo "✅ All local CI gates passed."

.PHONY: pre-commit
pre-commit: ## Run all pre-commit hooks across the repo
	pre-commit run --all-files

.PHONY: clean
clean: ## Remove caches and stray local Spark artifacts
	rm -rf .pytest_cache .ruff_cache spark-warehouse metastore_db
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	@echo "🧹 Cleaned caches and Spark scratch dirs."

# ==============================================================================
# Infrastructure — Terraform (delegates to terraform.sh)
# ==============================================================================
.PHONY: tf-fmt
tf-fmt: guard-LAYER ## terraform fmt for a LAYER
	./terraform.sh $(LAYER) fmt

.PHONY: plan
plan: guard-LAYER ## terraform plan for a LAYER (e.g. make plan LAYER=01_infra)
	./terraform.sh $(LAYER) plan

.PHONY: apply
apply: guard-LAYER ## terraform apply for a LAYER
	./terraform.sh $(LAYER) apply

.PHONY: destroy
destroy: guard-LAYER ## terraform destroy for a LAYER
	./terraform.sh $(LAYER) destroy

.PHONY: output
output: guard-LAYER ## Show terraform outputs for a LAYER
	./terraform.sh $(LAYER) output

.PHONY: infra-up
infra-up: ## Apply all 3 layers in the mandatory order (01 → 02 → 03)
	./terraform.sh 01_infra apply
	./terraform.sh 02_workspace apply
	./terraform.sh 03_unity_catalog apply

.PHONY: infra-down
infra-down: ## Destroy all 3 layers in reverse order (03 → 02 → 01)
	./terraform.sh 03_unity_catalog destroy
	./terraform.sh 02_workspace destroy
	./terraform.sh 01_infra destroy

# ==============================================================================
# Data pipeline — Databricks Asset Bundle (delegates to bundle.sh)
# ==============================================================================
.PHONY: validate
validate: ## Validate the DABs bundle against the workspace
	./bundle.sh validate

.PHONY: deploy
deploy: ## Deploy notebooks + job definition to Databricks
	./bundle.sh deploy

.PHONY: run
run: ## Trigger the Fleet Monitoring job and tail output
	./bundle.sh run
