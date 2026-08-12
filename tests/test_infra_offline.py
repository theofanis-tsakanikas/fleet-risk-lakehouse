"""Offline (no-apply) validation of the Terraform layers and the DABs bundle.

These checks never touch a cloud account:
  * ``terraform fmt -check`` is fully offline and is asserted (the repo uses the
    terraform_fmt pre-commit hook, so it must stay clean).
  * ``terraform validate -backend=false`` needs providers downloaded via
    ``terraform init -backend=false``; if that download can't happen (offline
    sandbox) the test self-skips rather than failing.
  * ``databricks bundle validate`` is schema-only here and is skipped when the CLI
    needs workspace auth that isn't present.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_LAYERS = ["01_infra", "02_workspace", "03_unity_catalog"]


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")
def test_terraform_fmt_check_whole_tree():
    # The whole terraform/ tree (layers + modules/) is pinned to the version in
    # .terraform-version and kept fmt-clean. -recursive descends into modules/.
    tf_dir = _ROOT / "terraform"
    result = _run(["terraform", "fmt", "-check", "-recursive"], tf_dir)
    assert (
        result.returncode == 0
    ), f"terraform fmt drift (run `terraform fmt -recursive terraform/`):\n{result.stdout}{result.stderr}"


@pytest.fixture(scope="session")
def terraform_tree(tmp_path_factory):
    """A throwaway copy of the whole terraform/ tree.

    ``terraform init`` rewrites ``.terraform.lock.hcl`` (adds local-platform
    provider hashes) and creates ``.terraform/``. We run validate against a copy
    so the tracked repo files are never mutated. The full tree is copied (not just
    one layer) to preserve the ``../../modules`` relative references.
    """
    dest = tmp_path_factory.mktemp("tf") / "terraform"
    shutil.copytree(
        _ROOT / "terraform",
        dest,
        ignore=shutil.ignore_patterns(".terraform"),
    )
    return dest


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")
@pytest.mark.parametrize("layer", _LAYERS)
def test_terraform_validate(layer, terraform_tree):
    layer_dir = terraform_tree / layer
    init = _run(["terraform", "init", "-backend=false", "-no-color", "-input=false"], layer_dir)
    if init.returncode != 0:
        pytest.skip(f"terraform init (provider download) unavailable offline:\n{init.stderr[-500:]}")
    result = _run(["terraform", "validate", "-no-color"], layer_dir)
    assert result.returncode == 0, f"terraform validate failed in {layer}:\n{result.stdout}{result.stderr}"


# --------------------------------------------------------------------------- #
# Storage hardening — asserted on the source, so it needs no cloud and no plan
# --------------------------------------------------------------------------- #

_FOUNDATION = _ROOT / "terraform" / "modules" / "aws_foundation" / "main.tf"

# Both buckets hold data that cannot be regenerated: the landing zone is read once
# by Auto Loader, and the metastore root is where every managed Delta table lives.
_BUCKETS = ["data_bucket", "metastore_bucket"]

_REQUIRED_CONTROLS = [
    ("aws_s3_bucket_public_access_block", "a public-access block"),
    ("aws_s3_bucket_server_side_encryption_configuration", "server-side encryption"),
    ("aws_s3_bucket_versioning", "versioning"),
]


@pytest.mark.parametrize("bucket", _BUCKETS)
@pytest.mark.parametrize("resource_type,description", _REQUIRED_CONTROLS)
def test_bucket_carries_its_baseline_controls(bucket, resource_type, description):
    """Each S3 bucket must declare all three controls, by name, in the module.

    Deleting one of these is a single-line change that no other test would notice —
    `terraform validate` is perfectly happy with an unencrypted, unversioned, public
    bucket. This asserts on the source text precisely because there is nothing to
    plan against while the estate is torn down.
    """
    source = _FOUNDATION.read_text()
    needle = f'resource "{resource_type}" "{bucket}"'
    assert (
        needle in source
    ), f"{bucket} no longer declares {description} — expected {needle} in terraform/modules/aws_foundation/main.tf"


def test_versioned_buckets_expire_their_noncurrent_versions():
    """Versioning without expiry turns a safety net into an unbounded bill."""
    source = _FOUNDATION.read_text()
    versioned = source.count('resource "aws_s3_bucket_versioning"')
    expiring = source.count("noncurrent_version_expiration")
    assert expiring >= versioned, (
        f"{versioned} bucket(s) have versioning enabled but only {expiring} lifecycle "
        f"rule(s) expire non-current versions."
    )


def test_prod_keeps_a_recovery_window_on_the_secret():
    """`recovery_window_in_days = 0` is a dev convenience; in prod it destroys the SPN."""
    source = _FOUNDATION.read_text()
    assert 'recovery_window_in_days = var.environment == "prod" ? 30 : 0' in source, (
        "The Secrets Manager recovery window is no longer environment-gated. A flat 0 "
        "means an accidental prod destroy takes the SPN credentials with it, "
        "unrecoverably."
    )


@pytest.mark.skipif(shutil.which("databricks") is None, reason="databricks CLI not installed")
def test_databricks_bundle_validate():
    result = _run(["databricks", "bundle", "validate", "-t", "dev"], _ROOT)
    if result.returncode != 0:
        combined = (result.stdout + result.stderr).lower()
        if any(tok in combined for tok in ("auth", "token", "host", "credential", "oauth", "login")):
            pytest.skip(f"bundle validate needs workspace auth (schema-only check skipped):\n{result.stderr[-400:]}")
        pytest.fail(f"databricks bundle validate failed:\n{result.stdout}{result.stderr}")
