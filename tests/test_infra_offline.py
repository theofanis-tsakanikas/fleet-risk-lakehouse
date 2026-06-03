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


@pytest.mark.skipif(shutil.which("databricks") is None, reason="databricks CLI not installed")
def test_databricks_bundle_validate():
    result = _run(["databricks", "bundle", "validate", "-t", "dev"], _ROOT)
    if result.returncode != 0:
        combined = (result.stdout + result.stderr).lower()
        if any(tok in combined for tok in ("auth", "token", "host", "credential", "oauth", "login")):
            pytest.skip(f"bundle validate needs workspace auth (schema-only check skipped):\n{result.stderr[-400:]}")
        pytest.fail(f"databricks bundle validate failed:\n{result.stdout}{result.stderr}")
