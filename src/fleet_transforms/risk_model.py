"""The driver risk model — single source of truth for the score and its explanation.

The Gold ``risk_score`` is a **transparent, explainable-by-design linear index**, not a
learned black box. For a safety-critical score that escalates a human (a fleet manager
contacting a driver), that is a deliberate, defensible choice: every point is traceable to
a factor and a weight, and the whole model fits on one page. This module is that page in
code — the weights, normalisation denominators, cap, and alert thresholds live here once,
and both the Gold SQL (``gold.py``) and the generated risk model card
(``fleet_governance``) are built from it, so the documentation can never drift from the
formula.

Score = ``min(cap, Σ factor_iᵢ)`` where ``factorᵢ = value / denominatorᵢ × weightᵢ`` and
NULL sensor readings contribute 0. The same arithmetic is exposed three ways — pure Python
(``score`` / ``contribution``, for tests and the model card), and SQL fragment builders
(for the Gold view) — so they are provably identical.

Explainability: alongside ``risk_score`` the Gold view now emits each factor's point
contribution and the single ``risk_primary_factor`` that drove the score, so a high-risk
driver can be explained ("32 of 71 points from speed"), not just flagged.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskFactor:
    """One additive component of the risk score."""

    name: str  # logical name (also the suffix of the Gold column: risk_<name>_pts)
    source_column: str  # the Silver/enriched column it reads
    weight: float  # max points this factor can contribute (before the cap)
    denominator: float  # value that maps to the full weight (the normaliser)

    def contribution(self, value: float | None) -> float:
        """Points this factor contributes for ``value`` (NULL → 0), rounded to 2 dp."""
        v = 0.0 if value is None else float(value)
        return round(v / self.denominator * self.weight, 2)


@dataclass(frozen=True)
class RiskModel:
    """The full risk model: factors, cap, version, and the alert thresholds."""

    version: str = "fleet-risk-index:v1"
    cap: float = 100.0
    factors: tuple[RiskFactor, ...] = (
        RiskFactor("speed", "speed", 40.0, 120.0),
        RiskFactor("stress", "stress_score", 35.0, 100.0),
        RiskFactor("heart_rate", "heart_rate", 25.0, 110.0),
    )
    # Alert thresholds (consumed by the safety-alerts SQL).
    overspeed: int = 90
    heart_rate_warning: int = 90
    heart_rate_danger: int = 110

    # -- pure Python (tests + model card) ---------------------------------- #

    def contributions(self, values: dict[str, float | None]) -> dict[str, float]:
        """Per-factor point contributions for a reading keyed by source column."""
        return {f.name: f.contribution(values.get(f.source_column)) for f in self.factors}

    def score(self, values: dict[str, float | None]) -> float:
        """The capped, rounded risk score for a reading."""
        raw = sum(self.contributions(values).values())
        return round(min(self.cap, raw), 2)

    def primary_factor(self, values: dict[str, float | None]) -> str:
        """The factor with the largest contribution ('none' when all are zero)."""
        contribs = self.contributions(values)
        if not any(contribs.values()):
            return "none"
        # ties resolve in declared factor order (speed > stress > heart_rate)
        return max(self.factors, key=lambda f: contribs[f.name]).name

    # -- SQL fragment builders (Gold view) --------------------------------- #

    def _term_sql(self, factor: RiskFactor, value_expr: str) -> str:
        """The un-rounded contribution expression for one factor."""
        return f"(COALESCE({value_expr}, 0) / {factor.denominator} * {factor.weight})"

    def risk_score_sql(self, exprs: dict[str, str]) -> str:
        """``risk_score`` SQL: capped sum of the factor terms, rounded to 2 dp.

        ``exprs`` maps each factor name to the qualified source expression in the
        enclosing SELECT (e.g. ``{"speed": "t.speed", ...}``).
        """
        terms = " +\n            ".join(self._term_sql(f, exprs[f.name]) for f in self.factors)
        return f"ROUND(\n        LEAST({self.cap},\n            {terms}\n        ), 2\n    )"

    def contribution_columns_sql(self, exprs: dict[str, str]) -> list[str]:
        """The ``risk_<name>_pts`` explainability columns, one per factor."""
        return [f"ROUND({self._term_sql(f, exprs[f.name])}, 2) AS risk_{f.name}_pts" for f in self.factors]

    def primary_factor_sql(self, exprs: dict[str, str]) -> str:
        """``risk_primary_factor``: the factor name with the greatest contribution."""
        terms = {f.name: self._term_sql(f, exprs[f.name]) for f in self.factors}
        names = [f.name for f in self.factors]
        cases = []
        # 'none' when every term is zero.
        cases.append(f"WHEN ({' + '.join(terms.values())}) = 0 THEN 'none'")
        for i, name in enumerate(names):
            # this factor wins if it's >= every other factor's term
            others = [terms[other] for j, other in enumerate(names) if j != i]
            conds = " AND ".join(f"{terms[name]} >= {o}" for o in others)
            cases.append(f"WHEN {conds} THEN '{name}'")
        body = "\n        ".join(cases)
        return f"CASE\n        {body}\n        ELSE '{names[-1]}'\n    END"


# The project's single configured model.
RISK_MODEL = RiskModel()
