import csv
import os
import random
import time
import boto3
import json
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

def parse_arguments():
    """Parses command line arguments with fallback to environment variables."""
    parser = argparse.ArgumentParser(description="Fleet Tracker Data Generator")
    
    parser.add_argument(
        "--bucket", 
        default=os.environ.get("DATA_LAKE_BUCKET"),
        help="S3 Bucket Name (Used for direct Boto3 upload)"
    )
    parser.add_argument(
        "--folder", 
        default=os.environ.get("S3_FOLDER_TRACKERS"),
        help="S3 Folder path for tracker data"
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
        default=os.environ.get("TRACKERS_LOCAL_DIR"),
        help="Local temporary directory for CSV files"
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
FOLDER_TRACKERS = args.folder
LOCAL_TEMP_DIR = args.local_dir
VOLUME_PATH = args.volume_path

os.makedirs(LOCAL_TEMP_DIR, exist_ok=True)

# Load Fleet Config
config_path = os.path.join(current_dir, "fleet_config.json")
try:
    with open(config_path, 'r') as f:
        fleet = json.load(f)
except FileNotFoundError:
    logger.error(f"fleet_config.json not found at {config_path}")
    sys.exit(1)

def generate_tracker_event(driver_info, synced_time):
    """Generates a tracker event synced to the same minute as watches."""
    id_roll = random.random()
    tracker_id = driver_info["tracker_id"]
    truck_id = driver_info["truck_id"]
    driver_id = driver_info["driver_id"]
    
    # ID Consistency & Error Logic
    if id_roll < 0.04:
        truck_id += "_ERR"
    elif id_roll < 0.07:
        driver_id = "DRV_999"
    elif id_roll < 0.10:
        tracker_id = ""
        
    # Coordinate Logic (Athens area defaults)
    coord_roll = random.random()
    if coord_roll < 0.05:
        lat, lon = 0.0, 0.0
    else:
        lat = round(37.9838 + random.uniform(-0.1, 0.1), 6)
        lon = round(23.7275 + random.uniform(-0.1, 0.1), 6)
    
    # Speed Logic
    speed_roll = random.random()
    if speed_roll < 0.05:
        speed = -1
    elif speed_roll < 0.10:
        speed = 999
    else:
        speed = random.randint(60, 95)

    status_options = ['Active', 'ACTIVE', 'MAINTENANCE', None]
    status = random.choice(status_options)

    return {
        "tracker_id": tracker_id,
        "truck_id": truck_id,
        "driver_id": driver_id,
        "latitude": lat,
        "longitude": lon,
        "speed": speed,
        "fuel_level": random.randint(10, 100),
        "status": status,
        "event_timestamp": synced_time.isoformat()
    }

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
    """Generates data for the fleet, saves to CSV, and pushes to Volume or S3."""
    events = [generate_tracker_event(driver, synced_time) for driver in fleet]
    
    if not events:
        return

    now_str = synced_time.strftime('%Y%m%d_%H%M%S')
    file_name = f"trackers_{now_str}.csv"
    local_file_path = os.path.join(LOCAL_TEMP_DIR, file_name)

    try:
        # 1. Save locally (CSV format)
        keys = events[0].keys()
        with open(local_file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(events)
        
        # 2. Hybrid Delivery Logic
        if VOLUME_PATH:
            # Map Root Volume + Subfolder from arguments
            dest_volume_path = os.path.join(VOLUME_PATH, file_name)
            
            # Create subdirectories in Volume if they don't exist
            os.makedirs(VOLUME_PATH, exist_ok=True)
            
            shutil.move(local_file_path, dest_volume_path)
            logger.info(f"Successfully moved to Volume: {dest_volume_path}")
        else:
            # Traditional S3 Upload
            s3_key = f"{FOLDER_TRACKERS}/{file_name}"
            if BUCKET_NAME and upload_to_s3(local_file_path, s3_key):
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

    logger.info("🎬 Starting Tracker Data Generation Simulation")
    
    delivery_mode = "Serverless (Volume)" if VOLUME_PATH else "Classic (S3 Boto3)"
    logger.info(f"Mode: {delivery_mode}, Batches: {num_batches}, Interval: {sleep_interval}s")
    
    for i in range(num_batches):
        # Sync timestamp to the start of the minute
        current_sync_time = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        logger.info(f"📦 Processing Batch {i+1}/{num_batches} at {current_sync_time}")
        
        save_and_push_batch(current_sync_time)
        
        if i < num_batches - 1:
            logger.info(f"💤 Sleeping for {sleep_interval} seconds...")
            time.sleep(sleep_interval)
            
    logger.info("✅ Simulation completed successfully!")