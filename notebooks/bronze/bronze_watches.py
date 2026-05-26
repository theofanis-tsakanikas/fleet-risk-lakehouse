# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # ⌚ Watches Bronze Ingestion (Auto Loader)
# MAGIC This notebook uses Databricks **Auto Loader** to incrementally ingest raw JSON files 
# MAGIC from S3 (via Unity Catalog Volumes) into a Bronze Delta Table.

# COMMAND ----------
import os
import logging
import sys
from databricks.connect import DatabricksSession
from pyspark.sql import functions as F

# --- DIRECTORY CONFIGURATION ---
# Use __file__ if available (standard Python), otherwise fallback to current working directory (Databricks)
if "__file__" in locals() or "__file__" in globals():
    current_dir = os.path.dirname(os.path.abspath(__file__))
else:
    current_dir = os.getcwd()

# --- HYBRID CONFIGURATION & LOCAL DEV SUPPORT ---
# We use a try-except block for 'python-dotenv' for local development support.
try:
    from dotenv import load_dotenv
    dotenv_path = os.path.join(current_dir, "../../.env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
except ImportError:
    pass

# --- LOGGER CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# === INITIALIZE SPARK SESSION ===
# Standard initialization for Databricks notebooks
logger.info("Connecting to Databricks Serverless Compute...")
spark = DatabricksSession.builder.serverless().getOrCreate()
logger.info("✅ Spark session initialized successfully!")

# COMMAND ----------
# === CONFIGURATION ===

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

try:
    catalog_name      = get_param("WATCHES_CATALOG")
    schema_name       = get_param("WATCHES_BRONZE_SCHEMA")
    volume_name       = get_param("WATCHES_BRONZE_VOLUME")
    table_name        = get_param("WATCHES_BRONZE_TABLE")
    metadata_schema   = get_param("WATCHES_METADATA_SCHEMA")
    checkpoint_volume = get_param("WATCHES_CHECKPOINT_VOLUME")
except KeyError as e:
    logger.error(f"Configuration error: {e}")
    raise

# Paths using Unity Catalog Volumes
volume_path = f"/Volumes/{catalog_name}/{schema_name}/{volume_name}"
output_table = f"{catalog_name}.{schema_name}.{table_name}"
# Checkpoint needs its own sub-directory to avoid conflicts
checkpoint_path = f"/Volumes/{catalog_name}/{metadata_schema}/{checkpoint_volume}/{table_name}"

logger.info(f"Target Bronze Table: {output_table}")
logger.info(f"Source Volume Path: {volume_path}")
logger.info(f"Enterprise Checkpoint Path: {checkpoint_path}")

# COMMAND ----------
# === READ STREAM (Auto Loader - cloudFiles) ===

logger.info("Starting Auto Loader to ingest JSON files...")

df_stream = (spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaLocation", f"{checkpoint_path}/schema")
    .option("cloudFiles.rescuedDataColumn", "_rescued_data")
    .load(volume_path)
)

# COMMAND ----------
# === ADD AUDIT COLUMNS ===

# We add metadata to track when data was ingested and from which file
df_bronze = (df_stream
    .withColumn("ingestion_timestamp", F.current_timestamp())
    .withColumn("source_file", F.col("_metadata.file_path"))
)

# COMMAND ----------
# === WRITE TO BRONZE DELTA TABLE ===

logger.info(f"Writing stream to: {output_table}...")

query = (df_bronze.writeStream
    .format("delta")
    .option("checkpointLocation", checkpoint_path)
    # AvailableNow=True: Processes all new files and stops (cost-efficient)
    .trigger(availableNow=True)
    .outputMode("append")
    .toTable(output_table)
)

query.awaitTermination()
logger.info("✅ Bronze Ingestion completed successfully!")