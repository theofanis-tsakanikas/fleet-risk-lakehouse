"""Local-Spark tests for the Silver cleansing transforms.

Exercises outlier nulling at the exact sentinel boundaries, deduplication,
status normalization, and pruning of corrupted IDs / ghost drivers — all against
a real local SparkSession with no infrastructure.
"""

import datetime as dt

from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from fleet_transforms.silver import transform_trackers_silver, transform_watches_silver

T0 = dt.datetime(2026, 6, 3, 12, 0, 0)
ING = dt.datetime(2026, 6, 3, 12, 5, 0)

_TRACKER_BRONZE_SCHEMA = StructType(
    [
        StructField("tracker_id", StringType()),
        StructField("truck_id", StringType()),
        StructField("driver_id", StringType()),
        StructField("latitude", DoubleType()),
        StructField("longitude", DoubleType()),
        StructField("speed", IntegerType()),
        StructField("fuel_level", IntegerType()),
        StructField("status", StringType()),
        StructField("event_timestamp", StringType()),
        StructField("ingestion_timestamp", TimestampType()),
        StructField("source_file", StringType()),
    ]
)

_METRICS_SCHEMA = StructType(
    [
        StructField("heart_rate", IntegerType()),
        StructField("steps", IntegerType()),
        StructField("battery_level", IntegerType()),
        StructField("stress_score", IntegerType()),
    ]
)

_WATCH_BRONZE_SCHEMA = StructType(
    [
        StructField("watch_id", StringType()),
        StructField("user_id", StringType()),
        StructField("event_timestamp", StringType()),
        StructField("metrics", _METRICS_SCHEMA),
        StructField("ingestion_timestamp", TimestampType()),
        StructField("source_file", StringType()),
    ]
)


def _tracker_row(**over):
    base = dict(
        tracker_id="GPS-SN-101",
        truck_id="TRK-701",
        driver_id="DRV_01",
        latitude=37.99,
        longitude=23.72,
        speed=80,
        fuel_level=50,
        status="Active",
        event_timestamp=T0.isoformat(),
        ingestion_timestamp=ING,
        source_file="s3://bucket/trackers_x.csv",
    )
    base.update(over)
    return tuple(base[f.name] for f in _TRACKER_BRONZE_SCHEMA.fields)


def _watch_row(heart_rate=80, steps=10, battery_level=70, stress_score=40, **over):
    base = dict(
        watch_id="WATCH_101",
        user_id="DRV_01",
        event_timestamp=T0.isoformat(),
        metrics=(heart_rate, steps, battery_level, stress_score),
        ingestion_timestamp=ING,
        source_file="s3://bucket/watches_x.json",
    )
    base.update(over)
    return tuple(base[f.name] for f in _WATCH_BRONZE_SCHEMA.fields)


def _trackers_df(spark, rows):
    return spark.createDataFrame(rows, schema=_TRACKER_BRONZE_SCHEMA)


def _watches_df(spark, rows):
    return spark.createDataFrame(rows, schema=_WATCH_BRONZE_SCHEMA)


# --------------------------------------------------------------------------- #
# Trackers
# --------------------------------------------------------------------------- #
def test_trackers_prune_err_truck_ghost_driver_and_missing_tracker(spark):
    rows = [
        _tracker_row(tracker_id="GPS-A", truck_id="TRK-701", driver_id="DRV_01"),  # keep
        _tracker_row(tracker_id="GPS-B", truck_id="TRK-701_ERR"),  # _ERR truck -> drop
        _tracker_row(tracker_id="GPS-C", driver_id="DRV_999"),  # ghost driver -> drop
        _tracker_row(tracker_id=""),  # empty tracker -> drop
        _tracker_row(tracker_id=None),  # null tracker -> drop
    ]
    out = transform_trackers_silver(_trackers_df(spark, rows))
    assert [r.tracker_id for r in out.collect()] == ["GPS-A"]


def test_trackers_speed_sentinels_nulled_at_boundaries(spark):
    rows = [
        _tracker_row(tracker_id="s-neg1", speed=-1),  # sentinel -> NULL
        _tracker_row(tracker_id="s-999", speed=999),  # sentinel -> NULL
        _tracker_row(tracker_id="s-998", speed=998),  # kept
        _tracker_row(tracker_id="s-200", speed=200),  # kept (no >200 rule for trackers)
        _tracker_row(tracker_id="s-0", speed=0),  # kept
    ]
    out = transform_trackers_silver(_trackers_df(spark, rows))
    by_id = {r.tracker_id: r.speed for r in out.collect()}
    assert by_id == {"s-neg1": None, "s-999": None, "s-998": 998, "s-200": 200, "s-0": 0}


def test_trackers_gps_zero_becomes_null(spark):
    rows = [
        _tracker_row(tracker_id="gz", latitude=0.0, longitude=0.0),
        _tracker_row(tracker_id="ok", latitude=37.9, longitude=23.7),
    ]
    collected = transform_trackers_silver(_trackers_df(spark, rows)).collect()
    out = {r.tracker_id: (r.latitude, r.longitude) for r in collected}
    assert out["gz"] == (None, None)
    assert out["ok"] == (37.9, 23.7)


def test_trackers_status_trimmed_and_uppercased(spark):
    rows = [
        _tracker_row(tracker_id="a", status="  active "),
        _tracker_row(tracker_id="b", status="ACTIVE"),
        _tracker_row(tracker_id="c", status=None),
    ]
    out = {r.tracker_id: r.status for r in transform_trackers_silver(_trackers_df(spark, rows)).collect()}
    assert out == {"a": "ACTIVE", "b": "ACTIVE", "c": None}


def test_trackers_dedup_on_tracker_id_and_timestamp(spark):
    rows = [_tracker_row(tracker_id="dup"), _tracker_row(tracker_id="dup")]
    out = transform_trackers_silver(_trackers_df(spark, rows))
    assert out.count() == 1


# --------------------------------------------------------------------------- #
# Watches
# --------------------------------------------------------------------------- #
def test_watches_prune_err_empty_null_ids_and_ghost_user(spark):
    rows = [
        _watch_row(watch_id="WATCH_101", user_id="DRV_01"),  # keep
        _watch_row(watch_id="WATCH_101_ERR"),  # _ERR -> drop
        _watch_row(watch_id="", event_timestamp=(T0 + dt.timedelta(seconds=1)).isoformat()),  # empty -> drop
        _watch_row(watch_id=None, event_timestamp=(T0 + dt.timedelta(seconds=2)).isoformat()),  # null -> drop
        _watch_row(watch_id="WATCH_102", user_id="DRV_999"),  # ghost user -> drop
    ]
    out = transform_watches_silver(_watches_df(spark, rows))
    assert [r.watch_id for r in out.collect()] == ["WATCH_101"]


def test_watches_heart_rate_nulled_at_boundaries(spark):
    rows = [
        _watch_row(watch_id="hr-neg999", heart_rate=-999),  # -> NULL
        _watch_row(watch_id="hr-0", heart_rate=0),  # -> NULL
        _watch_row(watch_id="hr-221", heart_rate=221),  # > 220 -> NULL
        _watch_row(watch_id="hr-250", heart_rate=250),  # > 220 -> NULL
        _watch_row(watch_id="hr-220", heart_rate=220),  # boundary kept
        _watch_row(watch_id="hr-65", heart_rate=65),  # kept
    ]
    out = {r.watch_id: r.heart_rate for r in transform_watches_silver(_watches_df(spark, rows)).collect()}
    assert out == {
        "hr-neg999": None,
        "hr-0": None,
        "hr-221": None,
        "hr-250": None,
        "hr-220": 220,
        "hr-65": 65,
    }


def test_watches_metrics_flattened(spark):
    rows = [_watch_row(heart_rate=72, steps=33, battery_level=88, stress_score=55)]
    out = transform_watches_silver(_watches_df(spark, rows))
    row = out.collect()[0]
    assert (row.heart_rate, row.steps, row.battery_level, row.stress_score) == (72, 33, 88, 55)
    assert "metrics" not in out.columns


def test_watches_dedup_on_watch_id_and_timestamp(spark):
    rows = [_watch_row(watch_id="dup"), _watch_row(watch_id="dup")]
    out = transform_watches_silver(_watches_df(spark, rows))
    assert out.count() == 1
