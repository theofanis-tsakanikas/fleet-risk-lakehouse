# Local Test Suite

A professional, **infrastructure-free** test suite for the Fleet Monitoring
platform. Everything here runs on a laptop with **zero cloud, zero provisioning,
zero Databricks workspace** — pure Python logic is tested directly, and Spark
transforms run against a local PySpark session.

## Philosophy

Transformation **logic** is separated from **framework/cloud execution**:

| Tested module (importable, no Databricks globals) | Thin notebook / script layer (NOT run locally) |
|---|---|
| `src/mock_generator/generators.py` — event generation + anomaly injection | `producer_*.py` arg parsing, S3/Volume delivery |
| `src/fleet_transforms/silver.py` — `transform_*_silver(df)` | `readStream`/`writeStream`, `DatabricksSession` |
| `src/fleet_transforms/gold.py` — risk/join/dedup SQL builders + DQ guard | `CREATE … AS`, Unity Catalog, `spark.sql` wiring |

The functions take their `SparkSession`/`DataFrame` inputs as **parameters**, so
no `spark`/`dbutils` global is required. Auto Loader, streaming, and Unity
Catalog stay in the notebooks and are never executed by the tests.

## Requirements

- **Python 3.9+**
- **Java 17 (JDK)** on `PATH` / `JAVA_HOME` — required by the local Spark
  session. On macOS (Homebrew): `brew install openjdk@17` and
  `export JAVA_HOME=$(brew --prefix openjdk@17)`.

## Setup & run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # pyspark, pytest, ruff
.venv/bin/python -m pytest                       # run the suite
.venv/bin/ruff check src tests notebooks         # lint
```

> Install dev deps in a **separate** virtualenv from `requirements.txt`. The
> latter pins `databricks-connect`, which conflicts with a plain `pyspark`
> install needed for local Spark execution.

The Spark fixture (`tests/conftest.py`) is session-scoped and points its
warehouse + Derby metastore at pytest tmp dirs using the in-memory catalog, so
**no `spark-warehouse/` or `metastore_db/` is ever written into the repo**.

## Coverage map

| File | Area |
|---|---|
| `tests/test_mock_generators.py` | Emitted-record schema, fleet_config mappings, every anomaly branch, anomaly **rates**, seed determinism (pure Python) |
| `tests/test_silver_transforms.py` | Outlier nulling at sentinel boundaries, dedup, status trim/upper, ghost-driver / corrupted-ID pruning (local Spark) |
| `tests/test_gold_transforms.py` | risk_score formula + cap + COALESCE, ±60s join window, ROW_NUMBER dedup vs alerts keep-all, ValueError DQ |
| `tests/test_known_gotchas.py` | Regression tests for CLAUDE.md gotchas **1, 4, 6, 7** |
| `tests/test_infra_offline.py` | `terraform fmt -check` + `validate -backend=false` (no apply); `databricks bundle validate` (schema only) |

## Known Gotchas → tests

| Gotcha | Covered locally? | Test |
|---|---|---|
| 1 — Gold empty after run (0 join matches → ValueError) | ✅ | `test_gotcha_1_*` |
| 2 — Layer 02/03 auth on fresh clone | ❌ cloud/Secrets Manager | — |
| 3 — `bundle.sh` Host not found | ❌ needs Databricks host/env | — |
| 4 — `backend.tfvars` fallback is safe (inline `backend "s3"`) | ✅ static | `test_gotcha_4_*` |
| 5 — pre-commit `terraform_validate` needs providers | ❌ provider download / env | partially via `test_terraform_validate` (self-skips offline) |
| 6 — risk_score capped at 100; NULLs → 0 | ✅ | `test_gotcha_6_*` |
| 7 — ±60s window multiple matches; live_status dedups, alerts keep all | ✅ | `test_gotcha_7_*` |

Gotchas 2, 3 and 5 are credential/provider-download concerns that cannot be
reproduced without infrastructure, by design of this suite.
