"""Pipeline self-observability — metrics about the *run*, not just the data.

The pipeline scores how dangerously drivers operate, but nothing watched the pipeline
itself: how many rows each stage produced, how many were quarantined, what fraction of
watch events found a tracker match in the ±60s join, how null the sensor columns ran. When
a run silently halves its output, that is invisible until someone notices a sparse
dashboard. This module emits a small, tall (long-format) ``pipeline_metrics`` fact that a
Grafana panel can trend over time.

Tall format — one row per (run, stage, metric) — is deliberate: new metrics need no schema
change, and Grafana/SQL group by ``metric`` trivially. The builders here are pure (assemble
rows, build the null-rate SQL); the notebook does the counting and appends the rows.
"""

from __future__ import annotations

# DDL for the append-only metrics fact. Tall layout: a metric is identified by its name,
# so adding measures never migrates the table.
METRICS_SCHEMA_DDL = "run_id STRING, captured_at TIMESTAMP, stage STRING, metric STRING, value DOUBLE"


def metric_rows(
    run_id: str,
    captured_at,
    stage: str,
    measures: dict[str, float],
) -> list[tuple]:
    """Flatten a stage's measures into ``pipeline_metrics`` rows.

    Args:
        run_id: The job-run identifier (groups all metrics from one pipeline run).
        captured_at: ``datetime`` the metrics were taken (passed in — never wall-clocked
            here, so the function stays pure and unit-testable).
        stage: The producing stage (e.g. ``"gold"``).
        measures: ``{metric_name: numeric_value}``. Values are coerced to ``float``;
            ``None`` is skipped (an unmeasured metric is omitted, not stored as 0).

    Returns:
        One ``(run_id, captured_at, stage, metric, value)`` tuple per measure, in the
        order ``measures`` was given.
    """
    rows = []
    for name, value in measures.items():
        if value is None:
            continue
        rows.append((run_id, captured_at, stage, name, float(value)))
    return rows


def match_rate(matched: int, candidate: int) -> float:
    """Fraction of ``candidate`` rows that found a match (``0.0`` when there are none).

    Used for the join match rate (enriched rows vs. Silver watch rows) — a low value is the
    early-warning sign of timestamp skew between the two streams, the pipeline's main
    silent-failure mode.
    """
    if candidate <= 0:
        return 0.0
    return round(matched / candidate, 6)


def null_rate_select_sql(source: str, columns: list[str]) -> str:
    """SQL returning the total row count and the NULL fraction of each column.

    Produces one ``<col>_null_rate`` column per input, plus ``row_count``. Evaluated by the
    notebook against a Gold table so sensor-dropout (e.g. a wearable feed going dark) shows
    up as a rising null rate on the dashboard rather than as a quietly degraded risk score.

    Args:
        source: Table / view identifier to profile.
        columns: Columns to measure the null rate of.

    Returns:
        The SQL ``SELECT`` body (no surrounding DDL).
    """
    rate_cols = ",\n    ".join(
        f"ROUND(SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) / COUNT(*), 6) AS {c}_null_rate" for c in columns
    )
    return f"""
SELECT
    COUNT(*) AS row_count,
    {rate_cols}
FROM {source}
"""
