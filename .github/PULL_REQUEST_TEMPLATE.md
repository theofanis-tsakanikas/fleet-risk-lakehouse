## Summary

Briefly describe what this PR changes and why.

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that changes existing behaviour)
- [ ] Infrastructure / Terraform change
- [ ] Documentation only
- [ ] CI/CD change

## Affected Area

- [ ] Terraform (`01_infra` / `02_workspace` / `03_unity_catalog`)
- [ ] Databricks notebooks / DABs job
- [ ] Mock data generators
- [ ] CI/CD workflows
- [ ] Documentation

## Checklist

- [ ] I ran `pre-commit run --all-files` (or the relevant `terraform fmt` / `black` / `ruff` hooks).
- [ ] For Terraform changes, I reviewed the `terraform plan` output posted by the PR workflow for **all three layers**.
- [ ] I considered the mandatory layer apply order (`01 → 02 → 03`) and remote-state dependencies.
- [ ] I updated `CHANGELOG.md` under `[Unreleased]`.
- [ ] I updated documentation (`README.md` / `CLAUDE.md` / ADRs) where relevant.
- [ ] No secrets, credentials, or `.env` values are included in this PR.

## Related Issues

Closes #

## Notes for Reviewers

Anything reviewers should pay special attention to (e.g. data-quality impact, cost,
destroy ordering, schema changes to Gold tables).
