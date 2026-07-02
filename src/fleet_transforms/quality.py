"""A small declarative data-quality framework (expectations + quarantine).

The Gold layer used to guard itself with hand-rolled ``COUNT(*) ... raise ValueError``
snippets inline in the notebook. That works, but it conflates *detecting* a problem with
*reacting* to it, scatters the rules across the notebook, and can't tell you "12 rows are
bad, here they are" — it can only crash. This module replaces that with a declarative
suite, the same shape a reviewer expects from Great Expectations / Soda / DLT ``EXPECT``,
but with zero extra dependencies and fully testable on local Spark.

An :class:`Expectation` is a *named boolean SQL predicate that every valid row must
satisfy*, with a :class:`Severity`:

* ``ERROR`` — a violated row is invalid; it is **quarantined** (diverted to a side table),
  and if any ERROR expectation fails the run can be failed via :func:`enforce`.
* ``WARN`` — recorded and surfaced, but does not quarantine or fail the run.

The flow the Gold notebook uses:

    results = evaluate(df, suite)              # count violations per expectation
    valid, quarantine = split(df, suite)       # divide rows; quarantine is annotated
    enforce(results)                           # raise DataQualityError on ERROR failures

Keeping the predicates as SQL strings (evaluated with ``F.expr``) means the suite is
declarative and self-documenting, and the *exact same* predicate could be pushed into a
Delta ``CHECK`` constraint or a DLT ``EXPECT`` without translation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import reduce


class Severity(str, Enum):
    """How a violated expectation is treated."""

    ERROR = "error"  # quarantine the row; fail the run via enforce()
    WARN = "warn"  # record only; row flows through, run continues


@dataclass(frozen=True)
class Expectation:
    """A named boolean predicate every valid row must satisfy.

    Args:
        name: Stable identifier (used in metrics, quarantine annotations, logs).
        predicate_sql: A boolean SQL expression over the row. ``TRUE`` ⇒ the row is
            valid for this expectation. A ``NULL`` result is treated as a violation
            (a predicate that can't be evaluated does not get the benefit of the doubt).
        severity: :class:`Severity.ERROR` (quarantine + can fail) or ``WARN``.
        description: Human-readable intent, surfaced in the model/runbook docs.
    """

    name: str
    predicate_sql: str
    severity: Severity = Severity.ERROR
    description: str = ""


@dataclass(frozen=True)
class ExpectationResult:
    """The outcome of evaluating one :class:`Expectation` against a dataset."""

    expectation: Expectation
    total: int
    failed: int

    @property
    def passed(self) -> bool:
        return self.failed == 0

    @property
    def pass_rate(self) -> float:
        """Fraction of rows that satisfied the expectation (1.0 for an empty dataset)."""
        if self.total == 0:
            return 1.0
        return round((self.total - self.failed) / self.total, 6)


class DataQualityError(Exception):
    """Raised by :func:`enforce` when one or more ERROR expectations were violated."""


def _valid_col(predicate_sql: str):
    """A boolean Column that is TRUE only when the predicate is provably satisfied.

    ``COALESCE(predicate, FALSE)`` makes a NULL predicate count as a violation.
    """
    from pyspark.sql import functions as F

    return F.coalesce(F.expr(predicate_sql), F.lit(False))


def evaluate(df, expectations: list[Expectation]) -> list[ExpectationResult]:
    """Count violations for each expectation against ``df`` (one pass per expectation)."""
    total = df.count()
    results = []
    for exp in expectations:
        failed = df.filter(~_valid_col(exp.predicate_sql)).count()
        results.append(ExpectationResult(exp, total, failed))
    return results


def split(df, expectations: list[Expectation]):
    """Divide ``df`` into (valid, quarantine) on the ERROR expectations.

    Only :class:`Severity.ERROR` expectations divert rows. The quarantine frame gains a
    ``_dq_failures`` column: an array of the names of the ERROR expectations each row
    violated, so the side table is self-explaining. WARN expectations never quarantine.

    Returns:
        ``(valid_df, quarantine_df)``. If there are no ERROR expectations, every row is
        valid and the quarantine frame is empty (but still carries ``_dq_failures``).
    """
    from pyspark.sql import functions as F

    error_exps = [e for e in expectations if e.severity is Severity.ERROR]

    if not error_exps:
        valid = df
        quarantine = df.limit(0).withColumn("_dq_failures", F.array().cast("array<string>"))
        return valid, quarantine

    is_valid = reduce(lambda a, e: a & _valid_col(e.predicate_sql), error_exps, F.lit(True))
    # Per-row array of the ERROR expectations this row violated.
    failure_terms = [F.when(~_valid_col(e.predicate_sql), F.lit(e.name)) for e in error_exps]
    failures = F.array_compact(F.array(*failure_terms)) if failure_terms else F.array()

    valid = df.filter(is_valid)
    quarantine = df.filter(~is_valid).withColumn("_dq_failures", failures)
    return valid, quarantine


def enforce(results: list[ExpectationResult]) -> None:
    """Raise :class:`DataQualityError` if any ERROR expectation was violated.

    WARN violations never raise. The message lists each failed ERROR expectation with its
    violation count, so a failed run is immediately diagnosable from the task log.
    """
    breaches = [r for r in results if r.expectation.severity is Severity.ERROR and not r.passed]
    if not breaches:
        return
    lines = [
        f"  - {r.expectation.name}: {r.failed}/{r.total} rows violated " f"({r.expectation.predicate_sql})"
        for r in breaches
    ]
    raise DataQualityError("Gold DQ FAILED — ERROR expectations violated:\n" + "\n".join(lines))
