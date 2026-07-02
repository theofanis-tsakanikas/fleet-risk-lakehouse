"""Biometric data classification + the generated GDPR docs.

Ties the column classification to the live Gold schema (so an unclassified column fails
CI) and locks the special-category (Art. 9) tagging of the biometric fields.
"""

import datetime as dt
from pathlib import Path

from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from fleet_governance import classification, generate
from fleet_transforms.gold import enriched_view_select_sql

REPO_ROOT = Path(__file__).resolve().parent.parent
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


def _enriched_columns(spark) -> list[str]:
    spark.createDataFrame([("D1", "T1", T0, 1.0, 2.0, 90, 50)], _TRK).createOrReplaceTempView("t_s")
    spark.createDataFrame([("D1", T0, 80, 40)], _WCH).createOrReplaceTempView("w_s")
    return spark.sql(enriched_view_select_sql("t_s", "w_s")).columns


# --------------------------------------------------------------------------- #
# classification ↔ live schema
# --------------------------------------------------------------------------- #


def test_classification_matches_live_gold_columns(spark):
    cols = _enriched_columns(spark)
    errors = classification.validate_classification(cols)
    assert errors == [], f"classification out of sync with the Gold view: {errors}"


def test_biometrics_are_special_category():
    special = set(classification.special_category_columns())
    assert {"heart_rate", "stress_score"} <= special


def test_location_is_personal_data():
    personal = set(classification.personal_columns())
    assert {"latitude", "longitude", "driver_id"} <= personal


def test_unclassified_column_is_flagged():
    errors = classification.validate_classification([*classification.GOLD_COLUMNS, "surprise_col"])
    assert any("surprise_col" in e for e in errors)


def test_derived_columns_not_personal():
    idx = classification.classification_index()
    for col in ("risk_score", "risk_speed_pts", "risk_primary_factor"):
        assert not idx[col].is_personal


def test_metrics_classification_matches_live_metrics_columns(spark):
    # Lock the aggregate contract too: the columns safety_metrics_select_sql actually
    # produces must all be classified (and none stale) in METRICS_COLUMN_CLASSES.
    from fleet_transforms.gold import safety_metrics_select_sql

    _enriched_columns(spark)  # registers t_s / w_s and validates the enriched view
    spark.sql("CREATE OR REPLACE TEMPORARY VIEW gov_enriched AS" + enriched_view_select_sql("t_s", "w_s"))
    cols = spark.sql(safety_metrics_select_sql("gov_enriched")).columns
    errors = classification.validate_metrics_classification(cols)
    assert errors == [], f"metrics classification out of sync: {errors}"


def test_aggregates_inherit_special_category():
    # Per-driver aggregation does not de-identify: Art. 9 handling flows through.
    midx = classification.metrics_classification_index()
    assert midx["avg_heart_rate"].is_special_category
    assert midx["avg_stress"].is_special_category
    assert not midx["max_speed"].is_personal
    assert not midx["avg_risk_score"].is_personal


# --------------------------------------------------------------------------- #
# generated docs
# --------------------------------------------------------------------------- #


def test_processing_record_lists_special_category():
    doc = generate.render_processing_record()
    assert "Art. 30" in doc
    assert "heart_rate" in doc and "stress_score" in doc
    assert "Art. 9" in doc


def test_processing_record_documents_enforced_masking():
    doc = generate.render_processing_record()
    assert "column mask" in doc.lower()  # masking is described as a safeguard/measure
    assert "fleet_safety_officers" in doc  # the privileged group is named
    # Every masked column is listed in the record (generated from the classification).
    from fleet_governance.masking import masked_columns

    for col in masked_columns():
        assert col in doc


def test_model_card_documents_transparent_index():
    doc = generate.render_risk_model_card()
    assert "not a learned model" in doc.lower() or "**not** a learned model" in doc
    assert "risk_primary_factor" in doc
    assert "65.68" in doc  # worked example pulled from the live model


def test_committed_docs_in_sync():
    rc = generate.main(["--root", str(REPO_ROOT), "--check"])
    assert rc == 0, "docs/governance is stale — run `make govern-docs`"
