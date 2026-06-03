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

# --- DIRECTORY CONFIGURATION ---
# Use __file__ if available (standard Python), otherwise fallback to current working directory (Databricks)
if "__file__" in locals() or "__file__" in globals():
    current_dir = os.path.dirname(os.path.abspath(__file__))
else:
    current_dir = os.getcwd()

# --- IMPORTABLE TRANSFORM LOGIC ---
# The Silver cleansing logic lives in a pure, unit-tested module under src/.
# The bundle ships src/ to the workspace; add it to sys.path so this notebook can
# import it. A wrong path surfaces loudly as an ImportError on the first run.
_SRC = os.path.abspath(os.path.join(current_dir, "..", "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
from fleet_transforms.silver import transform_trackers_silver  # noqa: E402

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

df_silver = transform_trackers_silver(df_bronze)

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