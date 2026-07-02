"""Local-Spark tests for the declarative data-quality framework.

Covers expectation evaluation (violation counts, NULL predicate = violation), the
valid/quarantine split with its ``_dq_failures`` annotation, WARN vs ERROR semantics, and
the ``enforce`` raise. Also locks the Gold ``fleet_live_status`` suite built from RISK_MODEL.
"""

import datetime as dt

import pytest

from fleet_transforms.gold import live_status_expectations
from fleet_transforms.quality import (
    DataQualityError,
    Expectation,
    Severity,
    enforce,
    evaluate,
    split,
)


def _df(spark):
    # risk_score 150 is out of range; the NULL driver_id row violates the not-null rule.
    return spark.createDataFrame(
        [
            ("DRV_01", 10.0),
            ("DRV_02", 150.0),
            (None, 20.0),
        ],
        "driver_id string, risk_score double",
    )


def test_evaluate_counts_violations(spark):
    exps = [
        Expectation("id_not_null", "driver_id IS NOT NULL"),
        Expectation("score_in_range", "risk_score BETWEEN 0 AND 100"),
    ]
    results = {r.expectation.name: r for r in evaluate(_df(spark), exps)}
    assert results["id_not_null"].failed == 1
    assert results["score_in_range"].failed == 1
    assert results["id_not_null"].total == 3
    assert results["score_in_range"].pass_rate == round(2 / 3, 6)


def test_null_predicate_counts_as_violation(spark):
    # risk_score BETWEEN ... is NULL when driver_id-less? No — use a predicate that yields
    # NULL: comparing a NULL column. The (None, 20.0) row makes `driver_id = 'x'` NULL.
    exps = [Expectation("eq", "driver_id = 'DRV_01'")]
    [result] = evaluate(_df(spark), exps)
    # DRV_02 fails (FALSE) and the NULL row fails (NULL → treated as violation): 2 of 3.
    assert result.failed == 2


def test_split_quarantines_error_rows_with_annotation(spark):
    exps = [
        Expectation("id_not_null", "driver_id IS NOT NULL", Severity.ERROR),
        Expectation("score_in_range", "risk_score BETWEEN 0 AND 100", Severity.ERROR),
    ]
    valid, quarantine = split(_df(spark), exps)
    assert valid.count() == 1
    assert valid.collect()[0].driver_id == "DRV_01"

    q = {(r.driver_id, tuple(r._dq_failures)) for r in quarantine.collect()}
    assert ("DRV_02", ("score_in_range",)) in q
    assert (None, ("id_not_null",)) in q
    assert "_dq_failures" in quarantine.columns


def test_warn_expectations_do_not_quarantine(spark):
    exps = [Expectation("score_in_range", "risk_score BETWEEN 0 AND 100", Severity.WARN)]
    valid, quarantine = split(_df(spark), exps)
    assert valid.count() == 3  # WARN never diverts rows
    assert quarantine.count() == 0


def test_enforce_raises_only_on_error_breach(spark):
    exps = [
        Expectation("id_not_null", "driver_id IS NOT NULL", Severity.ERROR),
        Expectation("score_in_range", "risk_score BETWEEN 0 AND 100", Severity.WARN),
    ]
    results = evaluate(_df(spark), exps)
    with pytest.raises(DataQualityError, match="id_not_null"):
        enforce(results)


def test_enforce_passes_when_clean(spark):
    clean = spark.createDataFrame([("DRV_01", 10.0)], "driver_id string, risk_score double")
    exps = [Expectation("id_not_null", "driver_id IS NOT NULL", Severity.ERROR)]
    assert enforce(evaluate(clean, exps)) is None


# --------------------------------------------------------------------------- #
# Gold live_status suite (built from RISK_MODEL)
# --------------------------------------------------------------------------- #
def test_live_status_suite_quarantines_bad_rows(spark):
    ts = dt.datetime(2026, 6, 3, 12, 0, 0)
    df = spark.createDataFrame(
        [
            ("DRV_01", ts, 42.0, "speed"),
            ("DRV_02", ts, 150.0, "speed"),  # out of range
            (None, ts, 10.0, "none"),  # null id
        ],
        "driver_id string, timestamp timestamp, risk_score double, risk_primary_factor string",
    )
    suite = live_status_expectations()
    valid, quarantine = split(df, suite)
    assert valid.count() == 1
    assert quarantine.count() == 2
    with pytest.raises(DataQualityError):
        enforce(evaluate(df, suite))
