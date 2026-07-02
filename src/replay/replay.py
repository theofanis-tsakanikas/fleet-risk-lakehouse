"""Replay orchestration: real trips → the two fleet streams, pseudonymised and rebased.

Pipeline (all pure — file/S3 delivery lives in :mod:`replay.producer_replay`):

1. **Assign** VED vehicles onto the pseudonymised fleet roster (``fleet_config.json``):
   vehicles sorted for determinism, one driver each; no VED identifier survives past this
   layer (GDPR: pseudonymised at source, like the mock fleet).
2. **Timeline** each driver's trips back-to-back (a fixed gap between them), starting at
   the replay ``anchor`` — every driver starts driving at the anchor, so the fleet is
   immediately busy and a replay lasts ~the longest driver timeline, not a calendar week.
3. **Emit** tracker events (cadence-resampled real GPS/speed) and watch events (biometrics
   conditioned on the trip's real hard-braking/overspeed — see :mod:`replay.biometrics`)
   on the *same* tick grid, so every watch reading has a tracker reading inside the Gold
   join window by construction. The dict schemas are exactly the mock generators'.
"""

from __future__ import annotations

import zlib
from datetime import datetime, timedelta

from replay.biometrics import biometric_series, detect_harsh_brakes
from replay.ved import Trip, resample

# Idle gap inserted between a driver's consecutive trips on the replay timeline.
DEFAULT_TRIP_GAP_S = 120.0

# Tracker/watch reading cadence — matches the mock producers' one-batch-per-minute rhythm
# and the ±60s Gold temporal join window.
DEFAULT_CADENCE_S = 60.0


def assign_drivers(trips: list[Trip], fleet: list[dict]) -> dict[str, dict]:
    """Map VED vehicle ids onto fleet roster entries, deterministically.

    Vehicles are sorted (numerically where possible) and paired with the roster in order;
    vehicles beyond the roster size are left unassigned (their trips are skipped).

    Args:
        trips: Parsed trips (only their ``vehicle_id`` matters here).
        fleet: ``fleet_config.json`` entries (driver/truck/watch/tracker ids).

    Returns:
        ``{vehicle_id: fleet_entry}`` for the assigned vehicles.
    """
    vehicles = sorted({t.vehicle_id for t in trips}, key=lambda v: (len(v), v))
    return dict(zip(vehicles, fleet))


def build_timeline(trips: list[Trip], trip_gap_s: float = DEFAULT_TRIP_GAP_S) -> list[tuple[float, Trip]]:
    """Sequence one vehicle's trips back-to-back from t=0 (the anchor).

    Args:
        trips: One vehicle's trips, in any order (sorted here by dataset start time).
        trip_gap_s: Idle seconds between consecutive trips.

    Returns:
        ``(timeline_start_s, trip)`` pairs, ordered.
    """
    timeline = []
    cursor = 0.0
    for trip in sorted(trips, key=lambda t: t.start_offset_s):
        timeline.append((cursor, trip))
        cursor += trip.duration_s + trip_gap_s
    return timeline


def _seed(driver_id: str, trip: Trip) -> int:
    """Deterministic per-driver/trip seed (crc32 — stable across processes, unlike hash())."""
    return zlib.crc32(f"{driver_id}:{trip.vehicle_id}:{trip.trip_id}".encode())


def _fuel_level(elapsed_s: float, duration_s: float) -> int:
    """A documented proxy: linear ~25% drain over the trip (VED fuel-rate is often absent)."""
    fraction = elapsed_s / duration_s if duration_s > 0 else 0.0
    return max(10, min(100, round(100 - 25 * fraction)))


def replay_events(
    trips: list[Trip],
    fleet: list[dict],
    anchor: datetime,
    cadence_s: float = DEFAULT_CADENCE_S,
    trip_gap_s: float = DEFAULT_TRIP_GAP_S,
) -> tuple[list[dict], list[dict]]:
    """Emit the tracker and watch event streams for a replay run.

    Args:
        trips: Parsed VED trips.
        fleet: The fleet roster (``fleet_config.json`` entries).
        anchor: Replay t=0 (timezone-aware UTC recommended); both streams derive every
            timestamp from it, so two invocations with the same anchor align exactly.
        cadence_s: Reading cadence for both streams.
        trip_gap_s: Idle gap between a driver's consecutive trips.

    Returns:
        ``(tracker_events, watch_events)`` — dicts in exactly the mock generators'
        schemas, ordered by event time.
    """
    by_vehicle: dict[str, list[Trip]] = {}
    for trip in trips:
        by_vehicle.setdefault(trip.vehicle_id, []).append(trip)
    assignment = assign_drivers(trips, fleet)

    tracker_events: list[dict] = []
    watch_events: list[dict] = []
    for vehicle_id, driver_info in assignment.items():
        for timeline_start_s, trip in build_timeline(by_vehicle[vehicle_id], trip_gap_s):
            ticks = resample(trip, cadence_s)
            brakes = detect_harsh_brakes(trip.points)
            biometrics = biometric_series(ticks, brakes, seed=_seed(driver_info["driver_id"], trip))

            for tick, reading in zip(ticks, biometrics):
                event_time = anchor + timedelta(seconds=timeline_start_s + tick.offset_s)
                timestamp = event_time.isoformat()
                tracker_events.append(
                    {
                        "tracker_id": driver_info["tracker_id"],
                        "truck_id": driver_info["truck_id"],
                        "driver_id": driver_info["driver_id"],
                        "latitude": round(tick.latitude, 6) if tick.latitude is not None else None,
                        "longitude": round(tick.longitude, 6) if tick.longitude is not None else None,
                        "speed": round(tick.speed_kmh) if tick.speed_kmh is not None else None,
                        "fuel_level": _fuel_level(tick.offset_s, trip.duration_s),
                        "status": "Active",
                        "event_timestamp": timestamp,
                    }
                )
                watch_events.append(
                    {
                        "watch_id": driver_info["watch_id"],
                        "user_id": driver_info["driver_id"],
                        "event_timestamp": timestamp,
                        "metrics": {
                            "heart_rate": reading.heart_rate,
                            "steps": int(tick.offset_s // 30) % 50,
                            "battery_level": max(5, 95 - int(tick.offset_s // 120)),
                            "stress_score": reading.stress_score,
                        },
                    }
                )

    tracker_events.sort(key=lambda e: e["event_timestamp"])
    watch_events.sort(key=lambda e: e["event_timestamp"])
    return tracker_events, watch_events


def batch_by_minute(events: list[dict]) -> dict[str, list[dict]]:
    """Group events into one batch per minute (the producers' one-file-per-batch layout).

    Args:
        events: Event dicts with an ISO ``event_timestamp``.

    Returns:
        ``{"YYYYmmdd_HHMM00": [events...]}`` in chronological key order.
    """
    batches: dict[str, list[dict]] = {}
    for event in events:
        stamp = datetime.fromisoformat(event["event_timestamp"])
        key = stamp.strftime("%Y%m%d_%H%M00")
        batches.setdefault(key, []).append(event)
    return dict(sorted(batches.items()))
