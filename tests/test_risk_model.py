"""Risk model: Python parity, SQL parity, and the explainability columns.

The Python ``RiskModel.score`` / ``contributions`` and the Gold SQL built from the same
model must agree exactly — that is the guarantee that lets the generated model card
document the deployed formula.
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

from fleet_transforms.gold import enriched_view_select_sql
from fleet_transforms.risk_model import RISK_MODEL, RiskFactor, RiskModel

T0 = dt.datetime(2026, 6, 3, 12, 0, 0)

_TRK = StructType(
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
_WCH = StructType(
    [
        StructField("user_id", StringType()),
        StructField("event_timestamp", TimestampType()),
        StructField("heart_rate", IntegerType()),
        StructField("stress_score", IntegerType()),
    ]
)


def _enrich_row(spark, speed, stress, hr):
    spark.createDataFrame([("D1", "T1", T0, 37.9, 23.7, speed, 50)], _TRK).createOrReplaceTempView("t_s")
    spark.createDataFrame([("D1", T0, hr, stress)], _WCH).createOrReplaceTempView("w_s")
    return spark.sql(enriched_view_select_sql("t_s", "w_s")).collect()[0]


# --------------------------------------------------------------------------- #
# pure Python
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "speed, stress, hr, expected",
    [
        (120, 100, 110, 100.0),
        (60, None, None, 20.0),
        (None, None, None, 0.0),
        (90, 50, 80, 65.68),
        (0, 0, 0, 0.0),
        (200, 200, 200, 100.0),  # capped
    ],
)
def test_python_score(speed, stress, hr, expected):
    vals = {"speed": speed, "stress_score": stress, "heart_rate": hr}
    assert RISK_MODEL.score(vals) == expected


def test_python_contributions():
    c = RISK_MODEL.contributions({"speed": 90, "stress_score": 50, "heart_rate": 80})
    assert c == {"speed": 30.0, "stress": 17.5, "heart_rate": 18.18}


def test_python_primary_factor():
    assert RISK_MODEL.primary_factor({"speed": 90, "stress_score": 50, "heart_rate": 80}) == "speed"
    assert RISK_MODEL.primary_factor({"speed": 0, "stress_score": 100, "heart_rate": 0}) == "stress"
    assert RISK_MODEL.primary_factor({"speed": 0, "stress_score": 0, "heart_rate": 0}) == "none"


def test_factor_contribution_rounds():
    f = RiskFactor("x", "x", 25.0, 110.0)
    assert f.contribution(80) == 18.18
    assert f.contribution(None) == 0.0


def test_custom_model_changes_score():
    # Different weights → different score, proving the model is the single source.
    m = RiskModel(factors=(RiskFactor("speed", "speed", 100.0, 100.0),))
    assert m.score({"speed": 50}) == 50.0


# --------------------------------------------------------------------------- #
# SQL parity (the Gold view must match the Python model exactly)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "speed, stress, hr",
    [(90, 50, 80), (120, 100, 110), (200, 200, 200), (30, 10, 60)],
)
def test_sql_matches_python(spark, speed, stress, hr):
    row = _enrich_row(spark, speed, stress, hr)
    vals = {"speed": speed, "stress_score": stress, "heart_rate": hr}
    assert float(row.risk_score) == RISK_MODEL.score(vals)
    c = RISK_MODEL.contributions(vals)
    assert float(row.risk_speed_pts) == c["speed"]
    assert float(row.risk_stress_pts) == c["stress"]
    assert float(row.risk_heart_rate_pts) == c["heart_rate"]
    assert row.risk_primary_factor == RISK_MODEL.primary_factor(vals)


def test_sql_emits_explainability_columns(spark):
    row = _enrich_row(spark, 90, 50, 80)
    for col in ("risk_speed_pts", "risk_stress_pts", "risk_heart_rate_pts", "risk_primary_factor"):
        assert col in row.asDict()


def test_primary_factor_none_when_all_zero(spark):
    row = _enrich_row(spark, 0, 0, 0)
    assert row.risk_primary_factor == "none"
    assert float(row.risk_score) == 0.0
