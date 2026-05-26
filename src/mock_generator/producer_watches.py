import json
import os
import random
import time
import boto3
import sys
import argparse
import logging
import shutil
from datetime import datetime, timezone
from botocore.exceptions import NoCredentialsError

# --- DIRECTORY CONFIGURATION ---
# Use __file__ if available (standard Python), otherwise fallback to current working directory (Databricks)
if "__file__" in locals() or "__file__" in globals():
    current_dir = os.path.dirname(os.path.abspath(__file__))
else:
    current_dir = os.getcwd()

# --- HYBRID CONFIGURATION & LOCAL DEV SUPPORT ---
# We use a try-except block for 'python-dotenv' because it's a local development tool.
# On Databricks/Production, we pass configurations via CLI arguments or Environment Variables.
try:
    from dotenv import load_dotenv
    
    # Construct the path to the .env file located at the project root
    dotenv_path = os.path.join(current_dir, "../../.env")
    
    # Only attempt to load if the file actually exists (Local Environment)
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
except ImportError:
    # If the library is missing (common in Databricks Runtime), we simply skip it.
    pass

# --- LOGGER CONFIGURATION ---
# Setting up professional logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def parse_arguments():
    """Parses command line arguments with fallback to environment variables."""
    parser = argparse.ArgumentParser(description="Fleet Watch Data Generator")
    
    parser.add_argument(
        "--bucket", 
        default=os.environ.get("DATA_LAKE_BUCKET"),
        help="S3 Bucket Name (Used for direct Boto3 upload)"
    )
    parser.add_argument(
        "--folder", 
        default=os.environ.get("S3_FOLDER_WATCHES"),
        help="S3 Folder path"
    )
    parser.add_argument(
        "--batches", 
        type=int, 
        default=int(os.environ.get("SIM_NUM_BATCHES", "5")),
        help="Number of batches to run"
    )
    parser.add_argument(
        "--interval", 
        type=int, 
        default=int(os.environ.get("SIM_SLEEP_INTERVAL", "60")),
        help="Seconds between batches"
    )
    parser.add_argument(
        "--local-dir", 
        default=os.environ.get("WATCHES_LOCAL_DIR"),
        help="Local temporary directory for JSON files"
    )
    parser.add_argument(
        "--volume-path", 
        default=os.environ.get("DBX_VOLUME_PATH"),
        help="Databricks UC Volume path. If provided, Boto3 is skipped."
    )
    
    return parser.parse_args()

# Initialize arguments
args = parse_arguments()

BUCKET_NAME = args.bucket
FOLDER_WATCHES = args.folder
LOCAL_TEMP_DIR = args.local_dir
VOLUME_PATH = args.volume_path

os.makedirs(LOCAL_TEMP_DIR, exist_ok=True)

# Load Fleet Config (Source of truth for drivers)
config_path = os.path.join(current_dir, "fleet_config.json")
try:
    with open(config_path, 'r') as f:
        fleet = json.load(f)
except FileNotFoundError:
    logger.error(f"fleet_config.json not found at {config_path}")
    sys.exit(1)

def generate_watch_event(driver_info, synced_time):
    """Generates a single event synced to a specific timestamp."""
    id_roll = random.random()
    watch_id = driver_info["watch_id"]
    user_id = driver_info["driver_id"]
    
    # ID Consistency & Error Logic
    if id_roll < 0.04:
        watch_id += "_ERR" 
    elif id_roll < 0.07:
        user_id = "DRV_999" 
    elif id_roll < 0.10:
        watch_id = ""
    
    # Scenario: Normal or Dirty Data
    error_roll = random.random()
    if error_roll < 0.05:
        heart_rate = None
    elif error_roll < 0.08:
        heart_rate = -999
    elif error_roll < 0.10:
        heart_rate = 0
    elif error_roll < 0.12:
        heart_rate = 250
    else:
        heart_rate = random.randint(65, 95)

    event = {
        "watch_id": watch_id,
        "user_id": user_id,
        "event_timestamp": synced_time.isoformat(), 
        "metrics": {
            "heart_rate": heart_rate,
            "steps": random.randint(0, 50),
            "battery_level": random.randint(5, 100)
        }
    }

    if random.random() < 0.80:
        event["metrics"]["stress_score"] = random.randint(1, 100)

    return event

def upload_to_s3(local_file_path, s3_key):
    """Uploads a local file to S3 using Boto3."""
    s3_client = boto3.client('s3')
    try:
        s3_client.upload_file(local_file_path, BUCKET_NAME, s3_key)
        logger.info(f"Successfully uploaded to S3: s3://{BUCKET_NAME}/{s3_key}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload to S3: {e}")
        return False

def save_and_push_batch(synced_time):
    """Generates data, saves locally, then moves to Volume or S3."""
    events = [generate_watch_event(driver, synced_time) for driver in fleet]
    
    # Inject duplicates for testing
    if random.random() < 0.20:
        events.append(events[0])

    now_str = synced_time.strftime('%Y%m%d_%H%M%S')
    file_name = f"watches_{now_str}.json"
    local_file_path = os.path.join(LOCAL_TEMP_DIR, file_name)

    # 1. Save locally (JSON Lines format)
    try:
        with open(local_file_path, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        
        # 2. Decide delivery method: Unity Catalog Volume or Direct S3
        if VOLUME_PATH:
            # Databricks Serverless Way: Move to Volume
            dest_volume_path = os.path.join(VOLUME_PATH, file_name)
            
            # Ensure the Volume directory exists
            os.makedirs(VOLUME_PATH, exist_ok=True)
            
            shutil.move(local_file_path, dest_volume_path)
            logger.info(f"Successfully moved to Volume: {dest_volume_path}")
        else:
            # Local/Standard Way: Upload via Boto3
            s3_key = f"{FOLDER_WATCHES}/{file_name}"
            if not BUCKET_NAME:
                logger.error("S3 Bucket Name is missing for Boto3 upload.")
                return
                
            if upload_to_s3(local_file_path, s3_key):
                os.remove(local_file_path)

    except Exception as e:
        logger.error(f"Error during batch processing: {e}")

if __name__ == "__main__":
    # Validate configuration
    if not BUCKET_NAME and not VOLUME_PATH:
        logger.error("Either --bucket or --volume-path must be provided.")
        sys.exit(1)

    num_batches = args.batches
    sleep_interval = args.interval

    logger.info("🎬 Starting Watch Data Generation Simulation")
    
    delivery_mode = "Serverless (Volume)" if VOLUME_PATH else "Classic (S3 Boto3)"
    logger.info(f"Mode: {delivery_mode}, Batches: {num_batches}, Interval: {sleep_interval}s")
    
    for i in range(num_batches):
        # Syncing timestamp to the minute for consistency
        current_sync_time = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        logger.info(f"📦 Processing Batch {i+1}/{num_batches} at {current_sync_time}")
        
        save_and_push_batch(current_sync_time)
        
        if i < num_batches - 1:
            logger.info(f"💤 Sleeping for {sleep_interval} seconds...")
            time.sleep(sleep_interval)
            
    logger.info("✅ Simulation completed successfully!")