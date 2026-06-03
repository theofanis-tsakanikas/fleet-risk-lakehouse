"""Shared pytest fixtures for the local test suite.

The Spark fixture is a single session-scoped, single-threaded local PySpark
session. It writes its warehouse and Derby metastore into pytest tmp dirs and
uses the in-memory catalog, so running the suite never leaves a ``spark-warehouse/``
or ``metastore_db/`` directory in the repo. Requires Java 17 on PATH (see
docs/TESTING.md).
"""

import sys
from pathlib import Path

import pytest

# Make the extracted, infra-free modules importable without installing them:
#   - src/                      -> `fleet_transforms` package
#   - src/mock_generator/       -> `generators` module
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "src" / "mock_generator"))


@pytest.fixture(scope="session")
def spark(tmp_path_factory):
    """Session-scoped local SparkSession with throwaway warehouse + metastore."""
    from pyspark.sql import SparkSession

    warehouse_dir = tmp_path_factory.mktemp("spark_warehouse")
    derby_home = tmp_path_factory.mktemp("derby")

    session = (
        SparkSession.builder.master("local[1]")
        .appName("fleet-monitoring-tests")
        .config("spark.sql.warehouse.dir", str(warehouse_dir))
        .config("spark.sql.catalogImplementation", "in-memory")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.ui.enabled", "false")
        .config("spark.driver.extraJavaOptions", f"-Dderby.system.home={derby_home}")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()
