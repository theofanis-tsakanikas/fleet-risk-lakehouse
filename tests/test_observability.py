"""Tests for pipeline self-observability builders.

Pure-Python row flattening + match-rate maths, plus the null-rate SQL exercised on local
Spark so the produced ``<col>_null_rate`` columns are real, not just string-asserted.
"""

import datetime as dt

from fleet_transforms.observability import (
    match_rate,
    metric_rows,
    null_rate_select_sql,
)

T0 = dt.datetime(2026, 6, 3, 12, 0, 0)


def test_metric_rows_flattens_measures_in_order():
    rows = metric_rows("run-1", T0, "gold", {"enriched_rows": 100, "quarantined": 3})
    assert rows == [
        ("run-1", T0, "gold", "enriched_rows", 100.0),
        ("run-1", T0, "gold", "quarantined", 3.0),
    ]


def test_metric_rows_skips_none_values():
    rows = metric_rows("run-1", T0, "gold", {"a": 1, "b": None, "c": 2})
    assert [r[3] for r in rows] == ["a", "c"]


def test_match_rate_basic_and_zero_guard():
    assert match_rate(80, 100) == 0.8
    assert match_rate(0, 0) == 0.0  # no candidates → 0.0, no ZeroDivisionError


def test_null_rate_sql_computes_real_rates(spark):
    df = spark.createDataFrame(
        [
            ("DRV_01", 70),
            ("DRV_02", None),
            ("DRV_03", None),
            ("DRV_04", 90),
        ],
        "driver_id string, heart_rate int",
    )
    df.createOrReplaceTempView("g")
    out = spark.sql(null_rate_select_sql("g", ["heart_rate", "driver_id"])).collect()[0]
    assert out.row_count == 4
    assert float(out.heart_rate_null_rate) == 0.5
    assert float(out.driver_id_null_rate) == 0.0
