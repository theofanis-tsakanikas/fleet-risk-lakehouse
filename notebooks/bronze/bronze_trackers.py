# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # 🚛 Trackers Bronze Ingestion (Auto Loader)
# MAGIC This notebook uses Databricks **Auto Loader** to incrementally ingest raw CSV files 
# MAGIC from S3 (via Unity Catalog Volumes) into the Trackers Bronze Delta Table.

# COMMAND ----------
import os
import logging
import sys
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

# === 3. INITIALIZE SPARK SESSION ===
# Inside a Databricks job a UC-ready `spark` session already exists — reuse it.
# Only local development (VS Code / Databricks Connect) builds a new one.
if "spark" not in globals():
    logger.info("Connecting to Databricks Serverless Compute (Local Context)...")
    from databricks.connect import DatabricksSession

    spark = DatabricksSession.builder.serverless().getOrCreate()
else:
    logger.info("✅ Using existing Databricks Spark session")

# COMMAND ----------
# === 4. CONFIGURATION ===

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
    # We use specific env vars for Trackers to keep the pipelines decoupled
    catalog_name = get_param("TRACKERS_CATALOG")
    schema_name = get_param("TRACKERS_BRONZE_SCHEMA")
    volume_name = get_param("TRACKERS_BRONZE_VOLUME")
    table_name = get_param("TRACKERS_BRONZE_TABLE")
    metadata_schema = get_param("TRACKERS_METADATA_SCHEMA")
    checkpoint_volume = get_param("TRACKERS_CHECKPOINT_VOLUME")
except KeyError as e:
    logger.error(f"Configuration error: {e}")
    raise

# Paths using Unity Catalog Volumes
volume_path = f"/Volumes/{catalog_name}/{schema_name}/{volume_name}"
output_table = f"{catalog_name}.{schema_name}.{table_name}"
# Checkpoint path specific to trackers
checkpoint_path = f"/Volumes/{catalog_name}/{metadata_schema}/{checkpoint_volume}/{table_name}"

logger.info(f"Target Bronze Table: {output_table}")
logger.info(f"Source Volume Path: {volume_path}")
logger.info(f"Enterprise Checkpoint Path: {checkpoint_path}")

# COMMAND ----------
# === 5. READ STREAM (Auto Loader - cloudFiles) ===

logger.info("Starting Auto Loader to ingest CSV files...")

df_stream = (spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "csv")
    .option("header", "true") # Essential for CSV ingestion
    .option("cloudFiles.inferColumnTypes", "true") # Auto-detect types (int, double, etc.)
    .option("cloudFiles.schemaLocation", f"{checkpoint_path}/schema")
    .option("cloudFiles.rescuedDataColumn", "_rescued_data")
    .load(volume_path)
)

# COMMAND ----------
# === 6. ADD AUDIT COLUMNS ===

# Adding ingestion metadata for traceability
df_bronze = (df_stream
    .withColumn("ingestion_timestamp", F.current_timestamp())
    .withColumn("source_file", F.col("_metadata.file_path"))
)

# COMMAND ----------
# === 7. WRITE TO BRONZE DELTA TABLE ===

logger.info(f"Writing stream to: {output_table}...")

query = (df_bronze.writeStream
    .format("delta")
    .option("checkpointLocation", checkpoint_path)
    .trigger(availableNow=True) # Process new files and shut down
    .outputMode("append")
    .toTable(output_table)
)

query.awaitTermination()
logger.info("✅ Trackers Bronze Ingestion completed successfully!")