# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # 🥈 Trackers Silver Transformation
# MAGIC This notebook reads from the Trackers Bronze Delta Table, cleans GPS and speed outliers, 
# MAGIC normalizes status strings, and writes the sanitized data to the Silver Delta Table.

# COMMAND ----------
import os
import logging
import sys
from databricks.connect import DatabricksSession
from pyspark.sql import functions as F
from pyspark.sql.types import TimestampType, IntegerType, DoubleType

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
    catalog_name = get_param("TRACKERS_CATALOG")
    bronze_schema = get_param("TRACKERS_BRONZE_SCHEMA")
    silver_schema = get_param("TRACKERS_SILVER_SCHEMA")
    bronze_table_name = get_param("TRACKERS_BRONZE_TABLE")
    silver_table_name = get_param("TRACKERS_SILVER_TABLE")
    metadata_schema = get_param("TRACKERS_METADATA_SCHEMA")
    checkpoint_volume = get_param("TRACKERS_CHECKPOINT_VOLUME")
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

logger.info("Reading stream from Trackers Bronze Delta table...")
df_bronze = spark.readStream.table(bronze_table)

# COMMAND ----------
# === 6. DATA CLEANING & TRANSFORMATION ===

logger.info("Applying Silver cleaning rules for GPS, speed, and status...")

df_silver = (df_bronze
    # 1. Cast columns to proper types
    .withColumn("latitude", F.col("latitude").cast(DoubleType()))
    .withColumn("longitude", F.col("longitude").cast(DoubleType()))
    .withColumn("speed", F.col("speed").cast(IntegerType()))
    .withColumn("fuel_level", F.col("fuel_level").cast(IntegerType()))
    .withColumn("event_timestamp", F.col("event_timestamp").cast(TimestampType()))

    # 🧼 Rule 1: Filter out Malformed Truck IDs and Missing Tracker IDs
    .filter(
        (~F.col("truck_id").contains("_ERR")) & 
        (F.col("tracker_id") != "") & 
        (F.col("tracker_id").isNotNull()) &
        (F.col("driver_id") != "DRV_999") # Ensuring only valid drivers move to Silver
    )

    # 🧼 Rule 2: Handle GPS Failures (0.0, 0.0)
    # We replace 0 coordinates with NULL to avoid plotting errors
    .withColumn("latitude", F.when(F.col("latitude") == 0, F.lit(None)).otherwise(F.col("latitude")))
    .withColumn("longitude", F.when(F.col("longitude") == 0, F.lit(None)).otherwise(F.col("longitude")))

    # 🧼 Rule 3: Handle Speed Outliers
    # -1: Sensor Error -> NULL
    # 999: Glitch/Impossible speed -> NULL
    .withColumn("speed", 
        F.when(F.col("speed").isin([-1, 999]), F.lit(None)).otherwise(F.col("speed"))
    )

    # 🧼 Rule 4: Standardize Status Strings
    # Trim spaces and convert to uppercase (handles 'Active', 'ACTIVE', 'inactive ')
    .withColumn("status", F.upper(F.trim(F.col("status"))))

    # 🧼 Rule 5: Deduplication
    .dropDuplicates(["tracker_id", "event_timestamp"])

    # 2. Add Silver Processing Metadata
    .withColumn("processed_timestamp", F.current_timestamp())
    
    # 3. Final Column Selection
    .select(
        "tracker_id",
        "truck_id",
        "driver_id",
        "latitude",
        "longitude",
        "speed",
        "fuel_level",
        "status",
        "event_timestamp",
        "ingestion_timestamp",
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
    .trigger(availableNow=True)
    .toTable(silver_table)
)

query.awaitTermination()
logger.info("✅ Trackers Silver Transformation Complete!")