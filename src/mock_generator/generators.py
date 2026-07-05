"""Pure, importable event generators for the fleet mock producers.

This module holds the side-effect-free record-generation logic shared by the
``producer_trackers.py`` and ``producer_watches.py`` entry points. Keeping it
free of top-level execution (no argument parsing, no filesystem or S3 calls)
makes the anomaly-injection rules unit-testable locally with zero infrastructure.

The two ``generate_*_event`` functions are byte-for-byte equivalent to the logic
that previously lived inline in the producer scripts; the producers now import
from here so that runtime behavior is unchanged.
"""

import json
import os
import random
from datetime import datetime


def load_fleet_config(config_path: str) -> list[dict]:
    """Load the driver/device mapping list from ``fleet_config.json``.

    Args:
        config_path: Absolute or relative path to the fleet config JSON file.

    Returns:
        A list of driver/device mapping dicts (the single source of truth for
        which drivers, watches, trucks and trackers exist in the simulation).
    """
    with open(config_path, "r") as f:
        return json.load(f)


def default_config_path() -> str:
    """Return the path to ``fleet_config.json`` next to this module."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fleet_config.json")


def generate_tracker_event(driver_info: dict, synced_time: datetime) -> dict:
    """Generate a single tracker event synced to the same minute as watches.

    Randomly injects malformed values (error truck IDs, unknown driver, empty
    tracker ID, zeroed GPS coordinates, sentinel speeds, inconsistent status) to
    simulate real-world sensor noise.

    Args:
        driver_info: A driver/device mapping entry from ``fleet_config.json``.
        synced_time: The UTC timestamp (truncated to the minute) for the event.

    Returns:
        A dict representing one tracker telemetry record.
    """
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

    status_options = ["Active", "ACTIVE", "MAINTENANCE", None]
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
        "event_timestamp": synced_time.isoformat(),
    }


def generate_watch_event(driver_info: dict, synced_time: datetime) -> dict:
    """Generate a single watch biometric event synced to a specific timestamp.

    Randomly injects malformed values (error watch IDs, unknown user, empty watch
    ID, null/sentinel/outlier heart rates) and omits the stress score ~20% of the
    time to simulate real-world wearable data quality issues.

    Args:
        driver_info: A driver/device mapping entry from ``fleet_config.json``.
        synced_time: The UTC timestamp (truncated to the minute) for the event.

    Returns:
        A dict representing one watch biometric record with nested ``metrics``.
    """
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

    # Scenario: Normal, Dirty, or a genuine safety incident.
    # ~10% of readings are a real extreme-stress event: an elevated but physiologically plausible
    # heart rate (111-155 bpm) that SURVIVES Silver cleansing (the >220 outlier filter) and trips
    # the DANGER / CRITICAL alert path -> PagerDuty escalation. Without it, valid heart rates cap at
    # 95 bpm, so `DANGER: Extreme Heart Rate` (heart_rate > 110) could never fire on real data.
    error_roll = random.random()
    if error_roll < 0.05:
        heart_rate = None
    elif error_roll < 0.08:
        heart_rate = -999
    elif error_roll < 0.10:
        heart_rate = 0
    elif error_roll < 0.12:
        heart_rate = 250
    elif error_roll < 0.22:
        heart_rate = random.randint(111, 155)
    else:
        heart_rate = random.randint(65, 95)

    event = {
        "watch_id": watch_id,
        "user_id": user_id,
        "event_timestamp": synced_time.isoformat(),
        "metrics": {
            "heart_rate": heart_rate,
            "steps": random.randint(0, 50),
            "battery_level": random.randint(5, 100),
        },
    }

    if random.random() < 0.80:
        event["metrics"]["stress_score"] = random.randint(1, 100)

    return event
