"""Tests for the real-data replay layer (VED parsing, biometrics, orchestration).

The committed ``data/ved/ved_sample.csv`` is real telemetry (see ``data/ved/README.md``),
so the parser tests run against the genuine article, and the end-to-end test proves the
replayed streams survive the *production* Silver transforms and produce a non-empty Gold
enriched view — the temporal join works on trips that actually happened.
"""

import datetime as dt
from pathlib import Path

import pytest
from pyspark.sql.types import (
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from replay.biometrics import (
    HARSH_BRAKE_DECEL_KMH_S,
    biometric_series,
    detect_harsh_brakes,
)
from replay.replay import assign_drivers, batch_by_minute, build_timeline, replay_events
from replay.ved import Trip, TripPoint, load_trips, parse_ved

_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = _ROOT / "data" / "ved" / "ved_sample.csv"
ANCHOR = dt.datetime(2026, 7, 1, 12, 0, 0, tzinfo=dt.timezone.utc)

FLEET = [
    {
        "driver_id": f"DRV_{i:02d}",
        "watch_id": f"WATCH_1{i:02d}",
        "truck_id": f"TRK-7{i:02d}",
        "tracker_id": f"GPS-SN-1{i:02d}",
        "name": f"Driver {i}",
    }
    for i in range(1, 11)
]


def _ved_row(veh="8", trip="706", day="1.5", ts_ms="0", lat="42.28", lon="-83.70", speed="40"):
    return {
        "VehId": veh,
        "Trip": trip,
        "DayNum": day,
        "Timestamp(ms)": ts_ms,
        "Latitude[deg]": lat,
        "Longitude[deg]": lon,
        "Vehicle Speed[km/h]": speed,
    }


# --------------------------------------------------------------------------- #
# VED parsing
# --------------------------------------------------------------------------- #
def test_parse_ved_groups_and_orders_trips():
    rows = [
        _ved_row(ts_ms="2000", speed="50"),
        _ved_row(ts_ms="0", speed="40"),
        _ved_row(veh="9", trip="10", ts_ms="0", speed="30"),
    ]
    trips = parse_ved(rows)
    assert [(t.vehicle_id, t.trip_id) for t in trips] == [("8", "706"), ("9", "10")]
    assert [p.offset_s for p in trips[0].points] == [0.0, 2.0]  # sorted within trip


def test_parse_ved_nan_becomes_none():
    trips = parse_ved([_ved_row(lat="NaN", lon="NaN", speed="NaN")])
    point = trips[0].points[0]
    assert point.latitude is None and point.longitude is None and point.speed_kmh is None


def test_committed_sample_is_real_and_wellformed():
    trips = load_trips(str(SAMPLE))
    assert len(trips) == 18  # 10 vehicles, 18 trips (see data/ved/README.md)
    assert len({t.vehicle_id for t in trips}) == 10
    for trip in trips:
        assert 8 * 60 <= trip.duration_s <= 25 * 60  # selection criteria
        offsets = [p.offset_s for p in trip.points]
        assert offsets == sorted(offsets)
        # Ann Arbor, Michigan — the sample's de-identified GPS stays in that area.
        lats = [p.latitude for p in trip.points if p.latitude is not None]
        assert lats and all(42.0 < lat < 42.6 for lat in lats)


def test_resample_keeps_last_reading_per_bucket():
    trip = Trip(
        "8",
        "706",
        0.0,
        points=tuple(
            TripPoint(offset_s=s, latitude=42.0, longitude=-83.0, speed_kmh=float(s)) for s in (0, 30, 59, 61)
        ),
    )
    from replay.ved import resample

    ticks = resample(trip, cadence_s=60.0)
    assert [t.offset_s for t in ticks] == [59, 61]  # bucket-last of [0,60) and [60,120)


# --------------------------------------------------------------------------- #
# Event detection & biometrics
# --------------------------------------------------------------------------- #
def _series(speeds, step_s=1.0):
    return [TripPoint(offset_s=i * step_s, latitude=42.0, longitude=-83.0, speed_kmh=v) for i, v in enumerate(speeds)]


def test_detect_harsh_brakes_flags_steep_decel_only():
    # 60→40 in 1s = 20 km/h/s (event); 40→35 in 1s = 5 km/h/s (normal braking).
    events = detect_harsh_brakes(_series([60, 60, 40, 35]))
    assert events == [2.0]
    assert HARSH_BRAKE_DECEL_KMH_S < 20


def test_detect_harsh_brakes_skips_sensor_gaps():
    points = [
        TripPoint(offset_s=0.0, latitude=None, longitude=None, speed_kmh=90.0),
        TripPoint(offset_s=30.0, latitude=None, longitude=None, speed_kmh=0.0),  # 30s gap: dropout, not braking
    ]
    assert detect_harsh_brakes(points) == []


def test_biometrics_are_deterministic_and_in_silver_range():
    ticks = _series([50, 60, 70], step_s=60.0)
    a = biometric_series(ticks, events=[65.0], seed=42)
    b = biometric_series(ticks, events=[65.0], seed=42)
    assert a == b  # same seed, same stream
    for reading in a:
        assert 0 < reading.heart_rate <= 220  # survives Silver validity rules
        assert 1 <= reading.stress_score <= 100


def test_biometrics_respond_to_real_braking_events():
    ticks = _series([50] * 10, step_s=60.0)
    calm = biometric_series(ticks, events=[], seed=7)
    stressed = biometric_series(ticks, events=[299.0], seed=7)  # event just before tick 5
    # Identical seeds isolate the event response: the post-event reading is elevated.
    assert stressed[5].heart_rate > calm[5].heart_rate
    assert stressed[5].stress_score > calm[5].stress_score
    # And it decays: a few minutes later the response has faded.
    assert stressed[9].stress_score - calm[9].stress_score < stressed[5].stress_score - calm[5].stress_score


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def test_assign_drivers_is_deterministic_and_pseudonymising():
    trips = load_trips(str(SAMPLE))
    assignment = assign_drivers(trips, FLEET)
    assert assign_drivers(trips, FLEET) == assignment  # stable
    assert len(assignment) == 10


def test_build_timeline_sequences_trips_with_gap():
    t1 = Trip("8", "1", 100.0, points=(TripPoint(0.0, None, None, 10.0), TripPoint(600.0, None, None, 10.0)))
    t2 = Trip("8", "2", 50.0, points=(TripPoint(0.0, None, None, 10.0), TripPoint(300.0, None, None, 10.0)))
    timeline = build_timeline([t1, t2], trip_gap_s=120.0)
    # t2 starts earlier in the dataset, so it replays first; t1 follows after gap.
    assert [trip.trip_id for _, trip in timeline] == ["2", "1"]
    assert timeline[0][0] == 0.0
    assert timeline[1][0] == 300.0 + 120.0


def test_replay_streams_share_schema_and_tick_grid():
    trips = load_trips(str(SAMPLE))
    trackers, watches = replay_events(trips, FLEET, ANCHOR)

    from mock_generator.generators import generate_tracker_event, generate_watch_event

    mock_tracker = generate_tracker_event(FLEET[0], dt.datetime(2026, 7, 1, 12, 0))
    mock_watch = generate_watch_event(FLEET[0], dt.datetime(2026, 7, 1, 12, 0))
    assert set(trackers[0]) == set(mock_tracker)  # exact mock schema
    assert set(watches[0]) <= set(mock_watch) | {"metrics"}
    assert set(watches[0]["metrics"]) >= {"heart_rate", "stress_score", "steps", "battery_level"}

    # No VED identifier leaks through — only the pseudonymised fleet roster.
    fleet_drivers = {d["driver_id"] for d in FLEET}
    assert {e["driver_id"] for e in trackers} <= fleet_drivers

    # Both streams tick on the same grid: every watch reading has its tracker twin.
    assert {e["event_timestamp"] for e in watches} == {e["event_timestamp"] for e in trackers}


def test_batch_by_minute_groups_chronologically():
    trips = load_trips(str(SAMPLE))
    trackers, _ = replay_events(trips, FLEET, ANCHOR)
    batches = batch_by_minute(trackers)
    keys = list(batches)
    assert keys == sorted(keys)
    assert sum(len(b) for b in batches.values()) == len(trackers)
    assert keys[0] == "20260701_120000"  # replay starts at the anchor


# --------------------------------------------------------------------------- #
# End-to-end: real trips → production Silver transforms → Gold enriched view
# --------------------------------------------------------------------------- #
_TRK_BRONZE = StructType(
    [
        StructField("tracker_id", StringType()),
        StructField("truck_id", StringType()),
        StructField("driver_id", StringType()),
        StructField("latitude", StringType()),
        StructField("longitude", StringType()),
        StructField("speed", StringType()),
        StructField("fuel_level", StringType()),
        StructField("status", StringType()),
        StructField("event_timestamp", StringType()),
        StructField("ingestion_timestamp", TimestampType()),
        StructField("source_file", StringType()),
    ]
)
_WCH_BRONZE = StructType(
    [
        StructField("watch_id", StringType()),
        StructField("user_id", StringType()),
        StructField("event_timestamp", StringType()),
        StructField(
            "metrics",
            StructType(
                [
                    StructField("heart_rate", IntegerType()),
                    StructField("steps", IntegerType()),
                    StructField("battery_level", IntegerType()),
                    StructField("stress_score", IntegerType()),
                ]
            ),
        ),
        StructField("ingestion_timestamp", TimestampType()),
        StructField("source_file", StringType()),
    ]
)


@pytest.fixture(scope="module")
def replayed_slice():
    """A one-vehicle slice of the real sample, replayed (kept small for test speed)."""
    trips = load_trips(str(SAMPLE))
    first_vehicle = sorted({t.vehicle_id for t in trips}, key=lambda v: (len(v), v))[0]
    slice_trips = [t for t in trips if t.vehicle_id == first_vehicle]
    return replay_events(slice_trips, FLEET[:1], ANCHOR)


def test_real_replay_survives_silver_and_joins_in_gold(spark, replayed_slice):
    from fleet_transforms.gold import enriched_view_select_sql
    from fleet_transforms.silver import transform_trackers_silver, transform_watches_silver

    trackers, watches = replayed_slice
    ingested = dt.datetime(2026, 7, 1, 12, 30)

    trk_rows = [
        tuple(
            [
                *(str(e[k]) if e[k] is not None else None for k in ("tracker_id", "truck_id", "driver_id")),
                *(str(e[k]) if e[k] is not None else None for k in ("latitude", "longitude", "speed", "fuel_level")),
                e["status"],
                e["event_timestamp"],
                ingested,
                "replay.csv",
            ]
        )
        for e in trackers
    ]
    wch_rows = [
        (
            e["watch_id"],
            e["user_id"],
            e["event_timestamp"],
            (
                e["metrics"]["heart_rate"],
                e["metrics"]["steps"],
                e["metrics"]["battery_level"],
                e["metrics"]["stress_score"],
            ),
            ingested,
            "replay.json",
        )
        for e in watches
    ]

    silver_trk = transform_trackers_silver(spark.createDataFrame(trk_rows, _TRK_BRONZE))
    silver_wch = transform_watches_silver(spark.createDataFrame(wch_rows, _WCH_BRONZE))

    # The production cleansing keeps the real data (it is valid, not synthetic noise).
    assert silver_trk.count() == len(trackers)
    assert silver_wch.count() == len(watches)

    silver_trk.createOrReplaceTempView("replay_t_silver")
    silver_wch.createOrReplaceTempView("replay_w_silver")
    enriched = spark.sql(enriched_view_select_sql("replay_t_silver", "replay_w_silver"))

    rows = enriched.collect()
    assert len(rows) > 0  # the ±60s temporal join matches on real trips
    for row in rows:
        assert 0.0 <= float(row.risk_score) <= 100.0
