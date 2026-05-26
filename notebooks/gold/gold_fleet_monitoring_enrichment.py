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

spark.sql(f"""
CREATE OR REPLACE TEMPORARY VIEW fleet_enriched_view AS
SELECT 
    t.driver_id, 
    t.truck_id, 
    t.event_timestamp as timestamp,
    t.latitude, 
    t.longitude, 
    t.speed, 
    t.fuel_level,
    w.heart_rate, 
    w.stress_score
FROM {t_silver_path} t
INNER JOIN {w_silver_path} w 
    ON t.driver_id = w.user_id 
    AND t.event_timestamp BETWEEN w.event_timestamp - INTERVAL 60 SECONDS 
                          AND w.event_timestamp + INTERVAL 60 SECONDS
""")

# COMMAND ----------
# MAGIC %md
# MAGIC ### 2. Production Gold Tables
# MAGIC Writing the final business-ready tables.

# COMMAND ----------
logger.info(f"Updating Gold Tables in {gold_catalog}.{gold_schema}...")

# Table 1: Live Status (Latest record per driver)
spark.sql(f"""
CREATE OR REPLACE TABLE {live_status_table} AS
SELECT * EXCEPT(rn) FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY driver_id ORDER BY timestamp DESC) as rn
    FROM fleet_enriched_view
) WHERE rn = 1
""")

# Table 2: Hourly Safety Metrics (Aggregated)
spark.sql(f"""
CREATE OR REPLACE TABLE {safety_metrics_table} AS
SELECT 
    driver_id,
    CAST(window(timestamp, "1 hour").start AS TIMESTAMP) as hour_bucket,
    ROUND(AVG(heart_rate), 2) as avg_heart_rate,
    MAX(speed) as max_speed,
    ROUND(AVG(stress_score), 2) as avg_stress
FROM fleet_enriched_view
GROUP BY driver_id, hour_bucket
ORDER BY driver_id ASC, hour_bucket DESC
""")

# Table 3: Safety Alerts (Historical Log)
spark.sql(f"""
CREATE OR REPLACE TABLE {safety_alerts_table} AS
SELECT 
    timestamp, 
    driver_id, 
    truck_id, 
    speed, 
    heart_rate,
    CASE 
        WHEN speed > 90 AND heart_rate > 90 THEN 'CRITICAL: High Speed & Stress'
        WHEN heart_rate > 110 THEN 'DANGER: Extreme Heart Rate'
        WHEN heart_rate > 90 THEN 'WARNING: Elevated Heart Rate'
        WHEN speed > 90 THEN 'OVERSPEED'
        ELSE 'NORMAL'
    END as alert_type
FROM fleet_enriched_view
WHERE speed > 90 OR heart_rate > 90
ORDER BY timestamp DESC
""")

logger.info("✅ Gold Enrichment Complete!")