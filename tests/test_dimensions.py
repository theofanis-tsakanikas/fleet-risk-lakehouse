"""Tests for the SCD Type 2 driver dimension.

The pure-Python reference (:func:`apply_scd2`) is exercised across every transition — new
driver, unchanged, reassignment, quiet batch, idempotent re-run — and the current-assignment
source SELECT is run on local Spark. The Databricks MERGE string is structurally locked
(it needs Delta, which the local OSS-Spark session does not provide).
"""

import datetime as dt

from fleet_transforms.dimensions import (
    DIM_COLUMNS,
    DimRecord,
    apply_scd2,
    current_assignment_select_sql,
    scd2_merge_sql,
)

T0 = dt.datetime(2026, 6, 3, 12, 0, 0)
T1 = dt.datetime(2026, 6, 4, 12, 0, 0)
T2 = dt.datetime(2026, 6, 5, 12, 0, 0)


def _current(records, driver_id):
    return [r for r in records if r.driver_id == driver_id and r.is_current]


def test_new_driver_opens_current_version():
    out = apply_scd2([], {"DRV_01": "TRK-701"}, T0)
    assert out == [DimRecord("DRV_01", "TRK-701", T0, None, True)]


def test_unchanged_assignment_is_noop():
    existing = [DimRecord("DRV_01", "TRK-701", T0, None, True)]
    out = apply_scd2(existing, {"DRV_01": "TRK-701"}, T1)
    assert out == existing  # same truck → no new version, no mutation


def test_reassignment_closes_old_and_opens_new():
    existing = [DimRecord("DRV_01", "TRK-701", T0, None, True)]
    out = apply_scd2(existing, {"DRV_01": "TRK-702"}, T1)
    assert out == [
        DimRecord("DRV_01", "TRK-701", T0, T1, False),  # closed at T1
        DimRecord("DRV_01", "TRK-702", T1, None, True),  # new current
    ]
    assert len(_current(out, "DRV_01")) == 1  # exactly one open version


def test_driver_absent_from_snapshot_is_untouched():
    existing = [DimRecord("DRV_01", "TRK-701", T0, None, True)]
    out = apply_scd2(existing, {"DRV_02": "TRK-702"}, T1)
    assert DimRecord("DRV_01", "TRK-701", T0, None, True) in out  # DRV_01 preserved
    assert _current(out, "DRV_02") == [DimRecord("DRV_02", "TRK-702", T1, None, True)]


def test_closed_history_is_never_mutated():
    existing = [
        DimRecord("DRV_01", "TRK-701", T0, T1, False),
        DimRecord("DRV_01", "TRK-702", T1, None, True),
    ]
    out = apply_scd2(existing, {"DRV_01": "TRK-703"}, T2)
    # The original closed version survives byte-for-byte.
    assert DimRecord("DRV_01", "TRK-701", T0, T1, False) in out
    assert DimRecord("DRV_01", "TRK-702", T1, T2, False) in out
    assert _current(out, "DRV_01") == [DimRecord("DRV_01", "TRK-703", T2, None, True)]


def test_idempotent_rerun_produces_no_new_versions():
    existing = apply_scd2([], {"DRV_01": "TRK-701"}, T0)
    once = apply_scd2(existing, {"DRV_01": "TRK-701"}, T1)
    twice = apply_scd2(once, {"DRV_01": "TRK-701"}, T2)
    assert once == existing == twice


def test_current_assignment_picks_latest_per_driver(spark):
    df = spark.createDataFrame(
        [
            ("DRV_01", "TRK-701", T0),
            ("DRV_01", "TRK-702", T1),  # newer → wins
            ("DRV_02", "TRK-705", T0),
            ("DRV_03", None, T0),  # null truck → excluded
        ],
        "driver_id string, truck_id string, event_timestamp timestamp",
    )
    df.createOrReplaceTempView("t_silver")
    out = {r.driver_id: r.truck_id for r in spark.sql(current_assignment_select_sql("t_silver")).collect()}
    assert out == {"DRV_01": "TRK-702", "DRV_02": "TRK-705"}


def test_merge_sql_is_structurally_scd2():
    sql = scd2_merge_sql("fleet_dev.operations.dim_driver", "driver_updates", "current_timestamp()")
    assert "MERGE INTO fleet_dev.operations.dim_driver" in sql
    assert "UNION ALL" in sql  # the two-intent staging
    assert "dim.is_current = false" in sql  # closes the old version
    assert "WHEN NOT MATCHED THEN" in sql  # opens the new version
    assert DIM_COLUMNS == ("driver_id", "truck_id", "valid_from", "valid_to", "is_current")
