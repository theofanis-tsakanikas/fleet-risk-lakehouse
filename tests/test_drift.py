"""Tests for risk-score distribution drift detection.

Pure PSI maths (stable when distributions match, rising as they diverge, finite on empty
bands) + severity classification, plus the band-count SQL exercised on local Spark.
"""

from fleet_transforms.drift import (
    DEFAULT_BASELINE,
    PSI_SIGNIFICANT,
    assess_drift,
    band_counts_select_sql,
    classify_psi,
    psi,
)


def test_psi_zero_when_distributions_match():
    dist = {"band_0_25": 55, "band_25_50": 30, "band_50_75": 12, "band_75_100": 3}
    assert psi(dist, dist) == 0.0


def test_psi_rises_with_divergence():
    base = {"band_0_25": 55, "band_25_50": 30, "band_50_75": 12, "band_75_100": 3}
    mild = {"band_0_25": 50, "band_25_50": 32, "band_50_75": 13, "band_75_100": 5}
    severe = {"band_0_25": 10, "band_25_50": 20, "band_50_75": 30, "band_75_100": 40}
    assert psi(base, mild) < psi(base, severe)


def test_psi_is_finite_with_empty_band():
    base = {"band_0_25": 50, "band_25_50": 50, "band_50_75": 0, "band_75_100": 0}
    cur = {"band_0_25": 0, "band_25_50": 0, "band_50_75": 50, "band_75_100": 50}
    value = psi(base, cur)
    assert value > PSI_SIGNIFICANT  # a full shift is significant
    assert value != float("inf")  # epsilon guard keeps it finite


def test_classify_psi_thresholds():
    assert classify_psi(0.05) == "stable"
    assert classify_psi(0.15) == "moderate"
    assert classify_psi(0.40) == "significant"


def test_assess_drift_flags_significant_shift():
    current = {"band_0_25": 5, "band_25_50": 10, "band_50_75": 25, "band_75_100": 60}
    report = assess_drift(DEFAULT_BASELINE, current)
    assert report.severity == "significant"
    assert report.is_alerting
    # current proportions normalise to 1.0
    assert round(sum(report.current.values()), 6) == 1.0


def test_band_counts_sql_bins_scores(spark):
    df = spark.createDataFrame(
        [(10.0,), (20.0,), (40.0,), (60.0,), (80.0,), (100.0,)],
        "risk_score double",
    )
    df.createOrReplaceTempView("g")
    row = spark.sql(band_counts_select_sql("g")).collect()[0]
    assert row.band_0_25 == 2  # 10, 20
    assert row.band_25_50 == 1  # 40
    assert row.band_50_75 == 1  # 60
    assert row.band_75_100 == 2  # 80, 100 (cap included)
