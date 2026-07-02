"""Risk-score distribution drift detection (Population Stability Index).

The risk score escalates a human, so a sudden shift in its *distribution* matters: if 40% of
drivers jump into the top risk band overnight, the likely cause is a sensor recalibration or
a units bug upstream — not a fleet-wide safety collapse. Catching that needs distribution
monitoring, not a per-row check. This module scores drift between a baseline risk-score
distribution and the current run with the Population Stability Index (PSI), the standard
credit-risk drift metric, over fixed risk bands.

Drift is a **signal, not a failure**: the notebook records the PSI and bands to the
``pipeline_metrics`` fact and logs a warning at the moderate/significant thresholds, rather
than failing the run — a shifted-but-correct distribution should not block the pipeline.

The maths is pure and unit-tested; the band counting is a plain SQL ``SELECT`` that runs on
any Spark.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Risk bands (lower-inclusive, upper-exclusive; the top band includes the 100.0 cap).
RISK_BANDS: tuple[tuple[float, float], ...] = ((0.0, 25.0), (25.0, 50.0), (50.0, 75.0), (75.0, 100.01))

# PSI interpretation thresholds (industry convention).
PSI_MODERATE = 0.1  # 0.1–0.25: moderate shift — worth a look
PSI_SIGNIFICANT = 0.25  # > 0.25: significant shift — investigate

# A modest smoothing constant so an empty band does not send PSI to infinity.
_EPS = 1e-6

# Default modeled "normal" fleet mix — most drivers low-risk, a thin high-risk tail.
# Used as the baseline when no historical distribution is supplied.
DEFAULT_BASELINE: dict[str, float] = {
    "band_0_25": 0.55,
    "band_25_50": 0.30,
    "band_50_75": 0.12,
    "band_75_100": 0.03,
}


def band_label(low: float, high: float) -> str:
    """The metric/column name for a band, e.g. ``band_0_25``."""
    return f"band_{int(low)}_{int(min(high, 100))}"


def band_counts_select_sql(source: str, score_col: str = "risk_score") -> str:
    """SQL returning the row count in each risk band for ``source``.

    Produces one ``band_<lo>_<hi>`` count column per :data:`RISK_BANDS`. Runs on plain
    Spark, so the binning is directly testable; the notebook feeds the result to
    :func:`assess_drift`.
    """
    cols = ",\n    ".join(
        f"SUM(CASE WHEN {score_col} >= {lo:g} AND {score_col} < {hi:g} THEN 1 ELSE 0 END) " f"AS {band_label(lo, hi)}"
        for lo, hi in RISK_BANDS
    )
    return f"""
SELECT
    {cols}
FROM {source}
"""


def _proportions(counts: dict[str, float]) -> dict[str, float]:
    total = sum(counts.values())
    if total <= 0:
        # Uniform when there is nothing to measure (PSI against any baseline ≈ 0 later).
        n = len(counts)
        return {k: 1.0 / n for k in counts}
    return {k: v / total for k, v in counts.items()}


def psi(baseline: dict[str, float], current: dict[str, float]) -> float:
    """Population Stability Index between two band distributions (counts or proportions).

    ``PSI = Σ (cur% − base%) · ln(cur% / base%)`` over the shared bands, with both inputs
    normalised to proportions and a small epsilon guarding empty bands. Higher = more drift.
    """
    base = _proportions(baseline)
    cur = _proportions(current)
    total = 0.0
    for band in base:
        b = max(base.get(band, 0.0), _EPS)
        c = max(cur.get(band, 0.0), _EPS)
        total += (c - b) * math.log(c / b)
    return round(total, 6)


@dataclass(frozen=True)
class DriftReport:
    """The outcome of a drift assessment for one run."""

    psi: float
    severity: str  # "stable" | "moderate" | "significant"
    baseline: dict[str, float]
    current: dict[str, float]

    @property
    def is_alerting(self) -> bool:
        """True at the moderate threshold or above (worth surfacing to an operator)."""
        return self.psi >= PSI_MODERATE


def classify_psi(value: float) -> str:
    if value >= PSI_SIGNIFICANT:
        return "significant"
    if value >= PSI_MODERATE:
        return "moderate"
    return "stable"


def assess_drift(baseline: dict[str, float], current: dict[str, float]) -> DriftReport:
    """Compute PSI and classify the shift between ``baseline`` and ``current`` band counts."""
    value = psi(baseline, current)
    return DriftReport(value, classify_psi(value), _proportions(baseline), _proportions(current))
