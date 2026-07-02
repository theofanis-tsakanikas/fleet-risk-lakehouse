"""Real-data replay producer — VED trips in, tracker/watch batch files out.

The replay counterpart of ``producer_trackers.py`` / ``producer_watches.py``: instead of
synthesising random events it replays **real VED trips** (see ``data/ved/README.md``)
through the exact same file contracts (CSV batches for trackers, JSON Lines for watches),
delivered to a Databricks UC Volume (``--volume-path``) or to S3 via Boto3.

Both streams derive every timestamp from the ``--anchor`` instant, so the job can run one
task per stream (``--stream trackers`` / ``--stream watches``) with the same anchor —
Databricks injects ``{{job.start_time.iso_datetime}}``, identical for all tasks of a run —
and the two streams align tick-for-tick inside the Gold ±60s join window.

Run locally (writes both streams under ``data/temp/replay/``):

    PYTHONPATH=src python -m replay.producer_replay --stream both --out-dir data/temp/replay
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone

# Resolve imports both as a package (local: PYTHONPATH=src) and as a Databricks
# spark_python_task, where this script's directory lands on sys.path but src/ does not.
_SRC = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mock_generator.generators import load_fleet_config  # noqa: E402
from replay.replay import DEFAULT_CADENCE_S, DEFAULT_TRIP_GAP_S, batch_by_minute, replay_events  # noqa: E402
from replay.ved import load_trips  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE_CSV = os.path.join(_HERE, "..", "..", "data", "ved", "ved_sample.csv")
DEFAULT_FLEET_CONFIG = os.path.join(_HERE, "..", "mock_generator", "fleet_config.json")

TRACKER_FIELDS = (
    "tracker_id",
    "truck_id",
    "driver_id",
    "latitude",
    "longitude",
    "speed",
    "fuel_level",
    "status",
    "event_timestamp",
)


def parse_anchor(raw: str | None) -> datetime:
    """The replay t=0: an ISO instant, else now (UTC) truncated to the minute."""
    if raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fleet replay producer (real VED trips)")
    parser.add_argument("--stream", choices=("trackers", "watches", "both"), default="both")
    parser.add_argument("--source-csv", default=os.environ.get("REPLAY_SOURCE_CSV", DEFAULT_SOURCE_CSV))
    parser.add_argument("--fleet-config", default=DEFAULT_FLEET_CONFIG)
    parser.add_argument("--anchor", default=os.environ.get("REPLAY_ANCHOR"), help="ISO instant; default: now (UTC)")
    parser.add_argument("--cadence", type=float, default=DEFAULT_CADENCE_S, help="Reading cadence in seconds")
    parser.add_argument("--trip-gap", type=float, default=DEFAULT_TRIP_GAP_S, help="Gap between a driver's trips (s)")
    parser.add_argument("--volume-path", default=os.environ.get("DBX_VOLUME_PATH"), help="UC Volume destination")
    parser.add_argument("--bucket", default=os.environ.get("DATA_LAKE_BUCKET"), help="S3 bucket (Boto3 delivery)")
    parser.add_argument("--folder", default=None, help="S3 folder for the selected stream")
    parser.add_argument("--out-dir", default="data/temp/replay", help="Local staging directory")
    return parser.parse_args()


def write_tracker_batch(events: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRACKER_FIELDS)
        writer.writeheader()
        writer.writerows(events)


def write_watch_batch(events: list[dict], path: str) -> None:
    with open(path, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def deliver(local_path: str, file_name: str, args: argparse.Namespace) -> None:
    """Move the batch file to the UC Volume, or upload to S3, or leave it staged locally."""
    if args.volume_path:
        os.makedirs(args.volume_path, exist_ok=True)
        shutil.move(local_path, os.path.join(args.volume_path, file_name))
        logger.info(f"Delivered to Volume: {os.path.join(args.volume_path, file_name)}")
    elif args.bucket:
        import boto3

        key = f"{args.folder or 'landing-zone/replay'}/{file_name}"
        boto3.client("s3").upload_file(local_path, args.bucket, key)
        os.remove(local_path)
        logger.info(f"Uploaded to S3: s3://{args.bucket}/{key}")
    else:
        logger.info(f"Staged locally: {local_path}")


def main() -> None:
    args = parse_arguments()
    anchor = parse_anchor(args.anchor)
    os.makedirs(args.out_dir, exist_ok=True)

    source = os.path.abspath(args.source_csv)
    trips = load_trips(source)
    fleet = load_fleet_config(args.fleet_config)
    logger.info(f"🎬 Replaying {len(trips)} real trips for {len(fleet)} drivers (anchor={anchor.isoformat()})")

    trackers, watches = replay_events(trips, fleet, anchor, cadence_s=args.cadence, trip_gap_s=args.trip_gap)

    if args.stream in ("trackers", "both"):
        for key, batch in batch_by_minute(trackers).items():
            file_name = f"trackers_{key}.csv"
            local_path = os.path.join(args.out_dir, file_name)
            write_tracker_batch(batch, local_path)
            deliver(local_path, file_name, args)
    if args.stream in ("watches", "both"):
        for key, batch in batch_by_minute(watches).items():
            file_name = f"watches_{key}.json"
            local_path = os.path.join(args.out_dir, file_name)
            write_watch_batch(batch, local_path)
            deliver(local_path, file_name, args)

    logger.info("✅ Replay batches delivered.")


if __name__ == "__main__":
    main()
