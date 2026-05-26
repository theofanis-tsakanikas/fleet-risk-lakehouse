# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # 🥈 Watches Silver Transformation
# MAGIC This notebook cleans the raw Watch JSON data from Bronze, handles sensor errors, filters malformed IDs, 
# MAGIC and flattens the nested metrics for downstream analytics.

# COMMAND ----------
import os
import logging
import sys
from databricks.connect import DatabricksSession
from pyspark.sql import functions as F
from pyspark.sql.types import TimestampType, IntegerType

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
# Standard initialization for Databricks notebooks
logger.info("Connecting to Databricks Serverless Compute...")
spark = DatabricksSession.builder.serverless().getOrCreate()
logger.info("✅ Spark session initialized successfully!")

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
    catalog_name = get_param("WATCHES_CATALOG")
    bronze_schema = get_param("WATCHES_BRONZE_SCHEMA")
    silver_schema = get_param("WATCHES_SILVER_SCHEMA")
    bronze_table_name = get_param("WATCHES_BRONZE_TABLE")
    silver_table_name = get_param("WATCHES_SILVER_TABLE")
    metadata_schema = get_param("WATCHES_METADATA_SCHEMA")
    checkpoint_volume = get_param("WATCHES_CHECKPOINT_VOLUME")
except KeyError as e:
    logger.error(f"Configuration error: {e}")
    raise

bronze_table = f"{catalog_name}.{bronze_schema}.{bronze_table_name}"
silver_table = f"{catalog_name}.{silver_schema}.{silver_table_name}"
checkpoint_path = f"/Volumes/{catalog_name}/{metadata_schema}/{checkpoint_volume}/{silver_table_name}"

logger.info(f"Streaming from: {bronze_table}")
logger.info(f"Targeting: {silver_table}")

# COMMAND ----------
# === 5. READ FROM BRONZE (Streaming) ===

logger.info("Starting stream from Bronze Delta table...")
df_bronze = spark.readStream.table(bronze_table)

# COMMAND ----------
# === 6. DATA CLEANING & TRANSFORMATION ===

logger.info("Applying Silver cleaning rules and flattening metrics...")

df_silver = (df_bronze
    # 1. Flatten nested metrics and cast to proper types
    .withColumn("heart_rate", F.col("metrics.heart_rate").cast(IntegerType()))
    .withColumn("steps", F.col("metrics.steps").cast(IntegerType()))
    .withColumn("battery_level", F.col("metrics.battery_level").cast(IntegerType()))
    .withColumn("stress_score", F.col("metrics.stress_score").cast(IntegerType()))
    
    # 2. Convert event_timestamp from ISO string to Timestamp
    .withColumn("event_timestamp", F.col("event_timestamp").cast(TimestampType()))

    # 🧼 Rule 1: Filter out Malformed IDs (IDs containing '_ERR') or Missing IDs
    .filter(
        (~F.col("watch_id").contains("_ERR")) & 
        (F.col("watch_id") != "") & 
        (F.col("watch_id").isNotNull()) &
        (F.col("user_id") != "DRV_999") # Drop unknown drivers to keep Silver clean
    )

    # 🧼 Rule 2: Handle Invalid Sensor Data (Heart Rate)
    # -999: Hardware error -> NULL
    # 0: Dead sensor -> NULL
    # > 220: Impossible outlier -> NULL
    .withColumn("heart_rate", 
        F.when(F.col("heart_rate").isin([-999, 0]), F.lit(None))
         .when(F.col("heart_rate") > 220, F.lit(None))
         .otherwise(F.col("heart_rate"))
    )

    # 🧼 Rule 3: Deduplication (Handle the 20% duplicate injection from producer)
    # We use dropDuplicates on the unique event key
    .dropDuplicates(["watch_id", "event_timestamp"])

    # 3. Add Silver Processing Metadata
    .withColumn("processed_timestamp", F.current_timestamp())
    
    # 4. Final Column Selection
    .select(
        "watch_id",
        "user_id",
        "event_timestamp",
        "heart_rate",
        "steps",
        "battery_level",
        "stress_score",
        "ingestion_timestamp", # Originates from Bronze Auto Loader
        "processed_timestamp", 
        "source_file"
    )
)

# COMMAND ----------
# === 7. WRITE TO SILVER DELTA ===

logger.info(f"Writing sanitized stream to Silver: {silver_table}")

query = (df_silver.writeStream
    .format("delta")
    .option("checkpointLocation", checkpoint_path)
    .outputMode("append")
    .trigger(availableNow=True) # Process all new data and stop
    .toTable(silver_table)
)

query.awaitTermination()
logger.info("✅ Silver Watch Transformation Complete!")