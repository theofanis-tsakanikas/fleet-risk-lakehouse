"""Regression tests for the locally-reproducible items in CLAUDE.md "Known Gotchas".

Each test is named after the gotcha number it locks down. Gotchas 2, 3 and 5 are
cloud/credential/provider-download concerns and cannot be reproduced without
infrastructure — see docs/TESTING.md for the rationale.
"""

import datetime as dt
from pathlib import Path

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
)

T0 = dt.datetime(2026, 6, 3, 12, 0, 0)
_ROOT = Path(__file__).resolve().parents[1]

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


def _enrich(spark, trackers, watches, view="g_enriched"):
    spark.createDataFrame(trackers, _TRK_SCHEMA).createOrReplaceTempView("g_trk")
    spark.createDataFrame(watches, _WCH_SCHEMA).createOrReplaceTempView("g_wch")
    df = spark.sql(enriched_view_select_sql("g_trk", "g_wch"))
    df.createOrReplaceTempView(view)
    return df


# --------------------------------------------------------------------------- #
# Gotcha 1: Gold tables empty -> enriched view has 0 rows -> ValueError
# --------------------------------------------------------------------------- #
def test_gotcha_1_non_overlapping_timestamps_yield_empty_view_and_raise(spark):
    # Streams finished at different times: watch 10 minutes after the tracker.
    df = _enrich(
        spark,
        [("DRV_01", "TRK-701", T0, 37.9, 23.7, 80, 50)],
        [("DRV_01", T0 + dt.timedelta(minutes=10), 80, 40)],
    )
    count = df.count()
    assert count == 0
    with pytest.raises(ValueError, match="0 rows"):
        check_enriched_not_empty(count)


# --------------------------------------------------------------------------- #
# Gotcha 6: risk_score capped at 100; NULL sensors contribute 0 via COALESCE
# --------------------------------------------------------------------------- #
def test_gotcha_6_risk_capped_at_100(spark):
    df = _enrich(
        spark,
        [("DRV_01", "TRK-701", T0, 37.9, 23.7, 130, 50)],  # speed > 120
        [("DRV_01", T0, 130, 100)],  # hr > 110, stress = 100
    )
    assert df.collect()[0].risk_score == 100.0


def test_gotcha_6_null_sensors_coalesced_to_zero(spark):
    df = _enrich(
        spark,
        [("DRV_01", "TRK-701", T0, 37.9, 23.7, None, 50)],  # speed NULL
        [("DRV_01", T0, None, None)],  # hr + stress NULL
    )
    assert df.collect()[0].risk_score == 0.0


# --------------------------------------------------------------------------- #
# Gotcha 7: multiple tracker matches in the window -> live_status dedups to the
# most recent; safety_alerts keeps every row.
# --------------------------------------------------------------------------- #
def test_gotcha_7_multiple_matches_dedup_vs_keep_all(spark):
    watch_ts = T0
    trackers = [
        ("DRV_01", "TRK-701", watch_ts + dt.timedelta(seconds=10), 37.9, 23.7, 95, 50),
        ("DRV_01", "TRK-701", watch_ts + dt.timedelta(seconds=50), 37.9, 23.7, 99, 50),
    ]
    enriched = _enrich(spark, trackers, [("DRV_01", watch_ts, 95, 40)])
    assert enriched.count() == 2  # both tracker events fall inside ±60s

    # OSS Spark can't parse Databricks' `SELECT * EXCEPT(rn)`; relax only that
    # projection token and drop rn afterwards — the ROW_NUMBER dedup is unchanged.
    live_sql = live_status_select_sql("g_enriched").replace("* EXCEPT(rn)", "*")
    live = spark.sql(live_sql).drop("rn").collect()
    assert len(live) == 1
    assert live[0].timestamp == watch_ts + dt.timedelta(seconds=50)  # most recent

    alerts = spark.sql(safety_alerts_select_sql("g_enriched")).collect()
    assert len(alerts) == 2  # alerts log keeps all qualifying rows


# --------------------------------------------------------------------------- #
# Gotcha 4 (static): each layer's providers.tf carries an inline backend "s3"
# block, which is why the missing backend.tfvars fallback in terraform.sh is safe.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("layer", ["01_infra", "02_workspace", "03_unity_catalog"])
def test_gotcha_4_inline_s3_backend_block_present(layer):
    providers = (_ROOT / "terraform" / layer / "providers.tf").read_text()
    assert 'backend "s3"' in providers
