# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # 🏆 Fleet Monitoring Gold Layer
# MAGIC This notebook performs the final data enrichment by joining Trackers and Watches.
# MAGIC It uses a hybrid configuration to support both Local and Databricks environments.

# COMMAND ----------
import os
import logging
import sys
from databricks.connect import DatabricksSession

# --- LOGGER CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- DIRECTORY CONFIGURATION ---
if "__file__" in locals() or "__file__" in globals():
    current_dir = os.path.dirname(os.path.abspath(__file__))
else:
    current_dir = os.getcwd()

# --- IMPORTABLE GOLD LOGIC ---
# The risk_score / temporal-join / dedup SQL and the empty-view DQ guard live in a
# pure, unit-tested module under src/. The bundle ships src/ to the workspace; add
# it to sys.path. A wrong path surfaces loudly as an ImportError on the first run.
_SRC = os.path.abspath(os.path.join(current_dir, "..", "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
from fleet_transforms.gold import (  # noqa: E402
    check_enriched_not_empty,
    enriched_view_select_sql,
    live_status_select_sql,
    safety_alerts_select_sql,
    safety_metrics_select_sql,
)

# --- HYBRID CONFIGURATION (Local .env support) ---
try:
    from dotenv import load_dotenv
    dotenv_path = os.path.join(current_dir, "../../.env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
        logger.info("Loaded local .env file")
except ImportError:
    pass

# --- INITIALIZE SPARK ---
if "spark" not in globals():
    # For local development (e.g VS Code / Databricks Connect)
    logger.info("Connecting to Databricks Serverless Compute (Local Context)...")
    from databricks.connect import DatabricksSession
    spark = DatabricksSession.builder.serverless().getOrCreate()
else:
    # This runs inside Databricks (Jobs / Notebooks)
    # It uses the existing session that is UC-Ready
    logger.info("✅ Using existing Databricks Spark session")
    

# --- SAFE PARAMETER RETRIEVAL ---
def get_param(name):
    """
    Helper to get parameters from Databricks Widgets 
    with fallback to Environment Variables (for local development).
    
    This approach ensures the code is environment-agnostic.
    """
    # 1. Check if running in a Databricks environment by looking for dbutils in globals
    if "dbutils" in globals():
        try:
            # Attempt to retrieve the value from Databricks Widgets
            return dbutils.widgets.get(name)
        except Exception:
            # If widget is not defined, fall back to environment variables
            pass

    # 2. Fallback to Environment Variables (Local Dev or Cluster Env Vars)
    val = os.environ.get(name)
    
    if not val:
        logger.error(f"Missing parameter: {name}")
        raise KeyError(f"Parameter '{name}' not found in Databricks widgets or system environment variables.")
        
    return val

# === CONFIGURATION SETUP ===
try:
    gold_catalog    = get_param("GOLD_CATALOG")
    gold_schema     = get_param("GOLD_SCHEMA")
    gold_live_table = get_param("GOLD_LIVE_TABLE")
    gold_metrics_table = get_param("GOLD_METRICS_TABLE")
    gold_alerts_table = get_param("GOLD_ALERTS_TABLE")
    
    # Source Tables (Silver)
    w_silver_path = f"{get_param('WATCHES_CATALOG')}.{get_param('WATCHES_SILVER_SCHEMA')}.{get_param('WATCHES_SILVER_TABLE')}"
    t_silver_path = f"{get_param('TRACKERS_CATALOG')}.{get_param('TRACKERS_SILVER_SCHEMA')}.{get_param('TRACKERS_SILVER_TABLE')}"
    
    # Target Tables (Gold)
    live_status_table = f"{gold_catalog}.{gold_schema}.{gold_live_table}"
    safety_metrics_table = f"{gold_catalog}.{gold_schema}.{gold_metrics_table}"
    safety_alerts_table = f"{gold_catalog}.{gold_schema}.{gold_alerts_table}"

except KeyError as e:
    logger.error(f"Configuration error: {e}")
    raise

# COMMAND ----------
# MAGIC %md
# MAGIC ### 1. Unified Enriched View (Temporal Join)
# MAGIC We use a 1-minute interval to sync asynchronous Tracker and Watch events.

# COMMAND ----------
logger.info("Creating enriched temporary view...")
spark.sql(f"USE CATALOG {gold_catalog}")
spark.sql(f"USE SCHEMA {gold_schema}")

logger.info(f"Context locked to {gold_catalog}. Ready for JOIN.")

spark.sql(
    "CREATE OR REPLACE TEMPORARY VIEW fleet_enriched_view AS"
    + enriched_view_select_sql(t_silver_path, w_silver_path)
)

# COMMAND ----------
# --- DATA QUALITY: enriched view must not be empty ---
# An INNER JOIN with zero matches means the ±60s window found no correlated events.
# This is always a pipeline problem (timestamp skew, empty Silver tables) — not a
# valid business state — so we raise immediately rather than silently writing empty tables.
view_count = spark.sql("SELECT COUNT(*) AS cnt FROM fleet_enriched_view").collect()[0]["cnt"]
check_enriched_not_empty(view_count)
logger.info(f"DQ passed: fleet_enriched_view contains {view_count:,} rows.")

# COMMAND ----------
# MAGIC %md
# MAGIC ### 2. Production Gold Tables
# MAGIC Writing the final business-ready tables.

# COMMAND ----------
logger.info(f"Updating Gold Tables in {gold_catalog}.{gold_schema}...")

# Table 1: Live Status (Latest record per driver)
# risk_score flows through from fleet_enriched_view via SELECT * EXCEPT(rn).
spark.sql(
    f"CREATE OR REPLACE TABLE {live_status_table} AS"
    + live_status_select_sql("fleet_enriched_view")
)

# --- DATA QUALITY: fleet_live_status ---
null_keys = spark.sql(f"""
    SELECT COUNT(*) AS cnt FROM {live_status_table}
    WHERE driver_id IS NULL OR timestamp IS NULL
""").collect()[0]["cnt"]
if null_keys > 0:
    raise ValueError(
        f"Gold DQ FAILED: {live_status_table} has {null_keys} row(s) with NULL driver_id or timestamp."
    )
logger.info(f"DQ passed: no NULL key columns in {live_status_table}.")

out_of_range = spark.sql(f"""
    SELECT COUNT(*) AS cnt FROM {live_status_table}
    WHERE risk_score IS NULL OR risk_score < 0 OR risk_score > 100
""").collect()[0]["cnt"]
if out_of_range > 0:
    raise ValueError(
        f"Gold DQ FAILED: {live_status_table} has {out_of_range} row(s) with risk_score "
        f"outside [0.0, 100.0] or NULL. Check COALESCE handling in the enriched view formula."
    )
logger.info(f"DQ passed: all risk_score values in {live_status_table} are within [0.0, 100.0].")

# Table 2: Hourly Safety Metrics (Aggregated)
spark.sql(
    f"CREATE OR REPLACE TABLE {safety_metrics_table} AS"
    + safety_metrics_select_sql("fleet_enriched_view")
)

# --- DATA QUALITY: driver_safety_metrics ---
metrics_count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {safety_metrics_table}").collect()[0]["cnt"]
if metrics_count == 0:
    raise ValueError(
        f"Gold DQ FAILED: {safety_metrics_table} has 0 rows. "
        f"Unexpected given enriched view passed the non-empty check."
    )
logger.info(f"DQ passed: {safety_metrics_table} contains {metrics_count:,} rows.")

# Table 3: Safety Alerts (Historical Log)
# risk_score is included so Grafana alert panels can threshold on a single numeric column.
spark.sql(
    f"CREATE OR REPLACE TABLE {safety_alerts_table} AS"
    + safety_alerts_select_sql("fleet_enriched_view")
)

logger.info("✅ Gold Enrichment Complete!")