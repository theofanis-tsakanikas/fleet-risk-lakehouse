# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # 🧩 Driver Dimension (SCD Type 2)
# MAGIC Tracks the **history** of each driver's truck assignment as a slowly-changing
# MAGIC dimension. Each assignment is a versioned row with a validity interval; a
# MAGIC reassignment closes the old version and opens a new one (history is never
# MAGIC overwritten). The enriched Gold view is deliberately left unchanged — `dim_driver`
# MAGIC is a standalone conformed dimension that `fleet_live_status` and the dashboard can
# MAGIC join for as-of history.
# MAGIC
# MAGIC The SCD2 MERGE and the source snapshot query are imported from the pure, unit-tested
# MAGIC `fleet_transforms.dimensions` module.

# COMMAND ----------
import os
import logging
import sys

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

if "__file__" in locals() or "__file__" in globals():
    current_dir = os.path.dirname(os.path.abspath(__file__))
else:
    current_dir = os.getcwd()

_SRC = os.path.abspath(os.path.join(current_dir, "..", "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
from fleet_transforms.dimensions import (  # noqa: E402
    create_dim_table_sql,
    current_assignment_select_sql,
    scd2_merge_sql,
)

try:
    from dotenv import load_dotenv

    dotenv_path = os.path.join(current_dir, "../../.env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
        logger.info("Loaded local .env file")
except ImportError:
    pass

if "spark" not in globals():
    logger.info("Connecting to Databricks Serverless Compute (Local Context)...")
    from databricks.connect import DatabricksSession

    spark = DatabricksSession.builder.serverless().getOrCreate()
else:
    logger.info("✅ Using existing Databricks Spark session")


def get_param(name):
    if "dbutils" in globals():
        try:
            return dbutils.widgets.get(name)
        except Exception:
            pass
    val = os.environ.get(name)
    if not val:
        raise KeyError(
            f"Parameter '{name}' not found in Databricks widgets or system environment variables."
        )
    return val


def get_param_or(name, default):
    if "dbutils" in globals():
        try:
            return dbutils.widgets.get(name)
        except Exception:
            pass
    return os.environ.get(name, default)


# === CONFIGURATION ===
gold_catalog = get_param("GOLD_CATALOG")
gold_schema = get_param("GOLD_SCHEMA")
dim_table_name = get_param_or("DIM_DRIVER_TABLE", "dim_driver")

t_silver_path = f"{get_param('TRACKERS_CATALOG')}.{get_param('TRACKERS_SILVER_SCHEMA')}.{get_param('TRACKERS_SILVER_TABLE')}"
dim_table = f"{gold_catalog}.{gold_schema}.{dim_table_name}"

# COMMAND ----------
spark.sql(f"USE CATALOG {gold_catalog}")
spark.sql(f"USE SCHEMA {gold_schema}")

# 1) Ensure the SCD2 dimension table exists (no-op after the first run).
spark.sql(create_dim_table_sql(dim_table))

# 2) Stage the current driver→truck snapshot from Silver trackers.
spark.sql(
    "CREATE OR REPLACE TEMPORARY VIEW driver_updates AS"
    + current_assignment_select_sql(t_silver_path)
)
update_count = spark.sql("SELECT COUNT(*) AS c FROM driver_updates").collect()[0]["c"]
logger.info(f"Staged {update_count} current driver assignments from {t_silver_path}.")

# 3) Apply the SCD2 MERGE: close reassigned versions, open new ones, leave unchanged as-is.
#    A bound run timestamp is the change boundary (one consistent instant for the whole run).
effective_ts = "current_timestamp()"
spark.sql(scd2_merge_sql(dim_table, "driver_updates", effective_ts))

current_versions = spark.sql(
    f"SELECT COUNT(*) AS c FROM {dim_table} WHERE is_current = true"
).collect()[0]["c"]
total_versions = spark.sql(f"SELECT COUNT(*) AS c FROM {dim_table}").collect()[0]["c"]
logger.info(
    f"✅ dim_driver updated: {current_versions} current / {total_versions} total versions."
)
