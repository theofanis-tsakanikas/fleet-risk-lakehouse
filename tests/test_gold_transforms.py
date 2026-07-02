"""Local-Spark + pure-logic tests for the Gold enrichment layer.

Covers the risk_score formula (weights, LEAST cap at 100, COALESCE of NULLs),
the ±60s temporal join window, the ROW_NUMBER "latest per driver" dedup in
fleet_live_status vs. keep-all in fleet_safety_alerts, and the ValueError DQ guard
on an empty enriched view.
"""

import datetime as dt

import pytest
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from fleet_transforms.gold import (
    check_enriched_not_empty,
    enriched_view_select_sql,
    live_status_select_sql,
    safety_alerts_select_sql,
    safety_metrics_select_sql,
)

T0 = dt.datetime(2026, 6, 3, 12, 0, 0)

_TRK_SCHEMA = StructType(
    [
        StructField("driver_id", StringType()),
        StructField("truck_id", StringType()),
        StructField("event_timestamp", TimestampType()),
        StructField("latitude", DoubleType()),
        StructField("longitude", DoubleType()),
        StructField("speed", IntegerType()),
        StructField("fuel_level", IntegerType()),
    ]
)
_WCH_SCHEMA = StructType(
    [
        StructField("user_id", StringType()),
        StructField("event_timestamp", TimestampType()),
        StructField("heart_rate", IntegerType()),
        StructField("stress_score", IntegerType()),
    ]
)
_ENRICHED_SCHEMA = StructType(
    [
        StructField("driver_id", StringType()),
        StructField("truck_id", StringType()),
        StructField("timestamp", TimestampType()),
        StructField("latitude", DoubleType()),
        StructField("longitude", DoubleType()),
        StructField("speed", IntegerType()),
        StructField("fuel_level", IntegerType()),
        StructField("heart_rate", IntegerType()),
        StructField("stress_score", IntegerType()),
        StructField("risk_score", DoubleType()),
        # Explainability columns added to the enriched view (risk_model.py).
        StructField("risk_speed_pts", DoubleType()),
        StructField("risk_stress_pts", DoubleType()),
        StructField("risk_heart_rate_pts", DoubleType()),
        StructField("risk_primary_factor", StringType()),
    ]
)

# Default values for the four explainability columns, so existing 10-column
# synthetic enriched rows (which predate them) still satisfy the schema.
_EXPLAIN_DEFAULTS = (0.0, 0.0, 0.0, "none")


def _enrich(spark, trackers, watches):
    """Register silver-shaped rows as temp views and run the enriched SELECT."""
    spark.createDataFrame(trackers, _TRK_SCHEMA).createOrReplaceTempView("t_silver")
    spark.createDataFrame(watches, _WCH_SCHEMA).createOrReplaceTempView("w_silver")
    return spark.sql(enriched_view_select_sql("t_silver", "w_silver"))


def _enriched_view(spark, rows, name="enriched"):
    # Pad legacy 10-column rows with the explainability-column defaults.
    padded = [r + _EXPLAIN_DEFAULTS if len(r) == 10 else r for r in rows]
    spark.createDataFrame(padded, _ENRICHED_SCHEMA).createOrReplaceTempView(name)
    return name


def _run_live_status(spark, name):
    """Execute the production live_status query, verbatim, under OSS Spark.

    The projection enumerates the classified Gold contract columns (no Databricks
    ``* EXCEPT`` extension), so the exact production SQL runs locally.
    """
    return spark.sql(live_status_select_sql(name))


# --------------------------------------------------------------------------- #
# risk_score formula
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "speed, stress, hr, expected",
    [
        (120, 100, 110, 100.0),  # exactly the cap (40 + 35 + 25)
        (60, None, None, 20.0),  # 60/120*40, nulls -> 0
        (None, None, None, 0.0),  # all NULL -> 0
        (90, 50, 80, 65.68),  # 30 + 17.5 + 18.18 -> rounded
        (0, 0, 0, 0.0),
    ],
)
def test_risk_score_formula(spark, speed, stress, hr, expected):
    df = _enrich(
        spark,
        [("DRV_01", "TRK-701", T0, 37.9, 23.7, speed, 50)],
        [("DRV_01", T0, hr, stress)],
    )
    # risk_score is decimal (the SQL uses 100.0/120.0/...); compare as float.
    assert float(df.collect()[0].risk_score) == expected


def test_risk_score_capped_at_100(spark):
    # Uncapped would be 200/120*40 + 35 + 200/110*25 ≈ 147.1 -> LEAST clamps to 100.0
    df = _enrich(
        spark,
        [("DRV_01", "TRK-701", T0, 37.9, 23.7, 200, 50)],
        [("DRV_01", T0, 200, 100)],
    )
    assert float(df.collect()[0].risk_score) == 100.0


# --------------------------------------------------------------------------- #
# ±60s temporal join window
# --------------------------------------------------------------------------- #
def test_temporal_join_window_inclusive_boundaries(spark):
    watch_ts = T0
    trackers = [
        ("DRV_01", "TRK-701", watch_ts + dt.timedelta(seconds=59), 37.9, 23.7, 80, 50),
        ("DRV_01", "TRK-701", watch_ts + dt.timedelta(seconds=60), 37.9, 23.7, 81, 50),
        ("DRV_01", "TRK-701", watch_ts + dt.timedelta(seconds=61), 37.9, 23.7, 82, 50),
    ]
    df = _enrich(spark, trackers, [("DRV_01", watch_ts, 80, 40)])
    speeds = sorted(r.speed for r in df.collect())
    assert speeds == [80, 81]  # +59 and +60 match; +61 falls outside


def test_temporal_join_no_match_outside_window(spark):
    df = _enrich(
        spark,
        [("DRV_01", "TRK-701", T0 + dt.timedelta(seconds=120), 37.9, 23.7, 80, 50)],
        [("DRV_01", T0, 80, 40)],
    )
    assert df.count() == 0


def test_temporal_join_requires_same_driver(spark):
    df = _enrich(
        spark,
        [("DRV_01", "TRK-701", T0, 37.9, 23.7, 80, 50)],
        [("DRV_02", T0, 80, 40)],
    )
    assert df.count() == 0


# --------------------------------------------------------------------------- #
# fleet_live_status: latest per driver via ROW_NUMBER
# --------------------------------------------------------------------------- #
def test_live_status_keeps_latest_per_driver(spark):
    rows = [
        ("DRV_01", "TRK-701", T0, 37.9, 23.7, 80, 50, 70, 40, 30.0),
        ("DRV_01", "TRK-701", T0 + dt.timedelta(seconds=30), 37.9, 23.7, 95, 50, 85, 60, 70.0),
        ("DRV_02", "TRK-702", T0, 37.9, 23.7, 60, 50, 65, 20, 20.0),
    ]
    name = _enriched_view(spark, rows)
    out = _run_live_status(spark, name).collect()
    latest = {r.driver_id: r.timestamp for r in out}
    assert latest == {"DRV_01": T0 + dt.timedelta(seconds=30), "DRV_02": T0}
    assert "rn" not in _run_live_status(spark, name).columns


def test_live_status_projects_exactly_the_classified_contract():
    # Static lock on the production SQL string: the projection is the classified
    # Gold contract (GOLD_COLUMNS), enumerated — never `*`, never an extra column.
    from fleet_governance.classification import GOLD_COLUMNS

    sql = live_status_select_sql("fleet_enriched_view")
    for col in GOLD_COLUMNS:
        assert col in sql
    assert "SELECT *," in sql  # only the inner ROW_NUMBER subquery selects *
    assert "* EXCEPT" not in sql  # portable SQL — runs verbatim on OSS Spark
    assert "ROW_NUMBER() OVER (PARTITION BY driver_id ORDER BY timestamp DESC)" in sql
    assert "WHERE rn = 1" in sql


# --------------------------------------------------------------------------- #
# fleet_safety_alerts: keeps every qualifying row + classifies
# --------------------------------------------------------------------------- #
def test_safety_alerts_keeps_all_qualifying_rows(spark):
    rows = [
        ("DRV_01", "TRK-701", T0, 37.9, 23.7, 95, 50, 95, 40, 80.0),  # CRITICAL
        ("DRV_01", "TRK-701", T0 + dt.timedelta(seconds=30), 37.9, 23.7, 95, 50, 95, 40, 80.0),  # CRITICAL (kept)
        ("DRV_02", "TRK-702", T0, 37.9, 23.7, 70, 50, 115, 40, 60.0),  # DANGER
        ("DRV_03", "TRK-703", T0, 37.9, 23.7, 70, 50, 70, 40, 20.0),  # below thresholds -> excluded
    ]
    name = _enriched_view(spark, rows)
    out = spark.sql(safety_alerts_select_sql(name)).collect()
    assert len(out) == 3  # the two DRV_01 rows are both retained
    alert_types = {(r.driver_id, r.alert_type) for r in out}
    assert ("DRV_01", "CRITICAL: High Speed & Stress") in alert_types
    assert ("DRV_02", "DANGER: Extreme Heart Rate") in alert_types


def test_safety_metrics_aggregates_per_driver_hour(spark):
    rows = [
        ("DRV_01", "TRK-701", T0, 37.9, 23.7, 80, 50, 70, 40, 30.0),
        ("DRV_01", "TRK-701", T0 + dt.timedelta(minutes=10), 37.9, 23.7, 100, 50, 90, 60, 70.0),
    ]
    name = _enriched_view(spark, rows)
    out = spark.sql(safety_metrics_select_sql(name)).collect()
    assert len(out) == 1  # same driver, same hour bucket
    row = out[0]
    assert row.max_speed == 100
    assert row.max_risk_score == 70.0
    assert row.avg_risk_score == 50.0


# --------------------------------------------------------------------------- #
# DQ guard
# --------------------------------------------------------------------------- #
def test_check_enriched_raises_on_zero_rows():
    with pytest.raises(ValueError, match="fleet_enriched_view has 0 rows"):
        check_enriched_not_empty(0)


def test_check_enriched_passes_on_nonzero_rows():
    assert check_enriched_not_empty(5) is None
