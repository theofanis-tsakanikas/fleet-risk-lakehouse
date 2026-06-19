"""Gold-layer enrichment logic (pure SQL builders + DQ guard).

These helpers return the **exact** SQL ``SELECT`` bodies used by the
``gold_fleet_monitoring_enrichment.py`` notebook, parametrized only on the table
/ view identifiers (which were already f-string-interpolated inline). The
notebook wraps each returned string in the same ``CREATE OR REPLACE
TEMPORARY VIEW`` / ``CREATE OR REPLACE TABLE`` statement, so runtime behavior is
unchanged. Returning the SELECT body (not the DDL) lets tests run the query
against local temp views and assert on the resulting DataFrame without creating
any managed tables, warehouse or metastore.

Identifier note: the source arguments are interpolated as raw SQL identifiers,
exactly as before. Pass fully-qualified table paths in production
(``catalog.schema.table``) or temp-view names in tests.

The ``risk_score`` arithmetic and the alert thresholds are not hard-coded here — they come
from :data:`fleet_transforms.risk_model.RISK_MODEL`, the single source of truth that also
produces the generated risk model card. The Gold view additionally emits the per-factor
point contributions (``risk_<factor>_pts``) and ``risk_primary_factor`` so a high-risk
driver is explainable, not merely flagged.
"""

from fleet_transforms.risk_model import RISK_MODEL

# Qualified source expressions for each risk factor inside the enriched SELECT.
_RISK_EXPRS = {"speed": "t.speed", "stress": "w.stress_score", "heart_rate": "w.heart_rate"}


def enriched_view_select_sql(t_silver_path: str, w_silver_path: str) -> str:
    """Return the SELECT defining ``fleet_enriched_view`` (temporal join + risk).

    Implements the ±60-second ``INNER JOIN`` between trackers and watches, the weighted
    ``risk_score`` (built from :data:`RISK_MODEL` — speed 40 / stress 35 / heart_rate 25,
    NULLs coalesced to 0, capped at 100), and the explainability columns: each factor's
    point contribution (``risk_speed_pts`` / ``risk_stress_pts`` / ``risk_heart_rate_pts``)
    and ``risk_primary_factor`` (the factor that drove the score).

    Args:
        t_silver_path: Trackers Silver table identifier (aliased ``t``).
        w_silver_path: Watches Silver table identifier (aliased ``w``).

    Returns:
        The SQL ``SELECT`` body (no surrounding DDL).
    """
    contribution_cols = ",\n    ".join(RISK_MODEL.contribution_columns_sql(_RISK_EXPRS))
    return f"""
SELECT
    t.driver_id,
    t.truck_id,
    t.event_timestamp as timestamp,
    t.latitude,
    t.longitude,
    t.speed,
    t.fuel_level,
    w.heart_rate,
    w.stress_score,
    {RISK_MODEL.risk_score_sql(_RISK_EXPRS)} AS risk_score,
    {contribution_cols},
    {RISK_MODEL.primary_factor_sql(_RISK_EXPRS)} AS risk_primary_factor
FROM {t_silver_path} t
INNER JOIN {w_silver_path} w
    ON t.driver_id = w.user_id
    AND t.event_timestamp BETWEEN w.event_timestamp - INTERVAL 60 SECONDS
                          AND w.event_timestamp + INTERVAL 60 SECONDS
"""


def live_status_select_sql(source: str) -> str:
    """Return the SELECT for ``fleet_live_status`` (latest record per driver).

    Keeps only the most recent enriched row per ``driver_id`` via
    ``ROW_NUMBER() ... ORDER BY timestamp DESC``; ``risk_score`` flows through.

    Args:
        source: The enriched-view identifier to read from.

    Returns:
        The SQL ``SELECT`` body (no surrounding DDL).
    """
    return f"""
SELECT * EXCEPT(rn) FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY driver_id ORDER BY timestamp DESC) as rn
    FROM {source}
) WHERE rn = 1
"""


def safety_metrics_select_sql(source: str) -> str:
    """Return the SELECT for ``driver_safety_metrics`` (hourly aggregates).

    Args:
        source: The enriched-view identifier to read from.

    Returns:
        The SQL ``SELECT`` body (no surrounding DDL).
    """
    return f"""
SELECT
    driver_id,
    CAST(window(timestamp, "1 hour").start AS TIMESTAMP) as hour_bucket,
    ROUND(AVG(heart_rate), 2) as avg_heart_rate,
    MAX(speed) as max_speed,
    ROUND(AVG(stress_score), 2) as avg_stress,
    ROUND(AVG(risk_score), 2) as avg_risk_score,
    MAX(risk_score) as max_risk_score
FROM {source}
GROUP BY driver_id, hour_bucket
ORDER BY driver_id ASC, hour_bucket DESC
"""


def safety_alerts_select_sql(source: str) -> str:
    """Return the SELECT for ``fleet_safety_alerts`` (historical alert log).

    Keeps every qualifying row (``speed > overspeed OR heart_rate > heart_rate_warning``)
    — no per-driver deduplication — classifies each into an ``alert_type``, and carries
    ``risk_primary_factor`` so each alert states which factor drove it. Thresholds come
    from :data:`RISK_MODEL`.

    Args:
        source: The enriched-view identifier to read from.

    Returns:
        The SQL ``SELECT`` body (no surrounding DDL).
    """
    overspeed = RISK_MODEL.overspeed
    hr_warn = RISK_MODEL.heart_rate_warning
    hr_danger = RISK_MODEL.heart_rate_danger
    return f"""
SELECT
    timestamp,
    driver_id,
    truck_id,
    speed,
    heart_rate,
    stress_score,
    risk_score,
    risk_primary_factor,
    CASE
        WHEN speed > {overspeed} AND heart_rate > {hr_warn} THEN 'CRITICAL: High Speed & Stress'
        WHEN heart_rate > {hr_danger} THEN 'DANGER: Extreme Heart Rate'
        WHEN heart_rate > {hr_warn} THEN 'WARNING: Elevated Heart Rate'
        WHEN speed > {overspeed} THEN 'OVERSPEED'
        ELSE 'NORMAL'
    END as alert_type
FROM {source}
WHERE speed > {overspeed} OR heart_rate > {hr_warn}
ORDER BY timestamp DESC
"""


def check_enriched_not_empty(view_count: int) -> None:
    """Raise if the enriched view is empty (Gold data-quality guard).

    An ``INNER JOIN`` with zero matches means the ±60s window found no correlated
    events — always a pipeline problem (timestamp skew, empty Silver tables), not
    a valid business state — so we raise rather than silently writing empty tables.

    Args:
        view_count: Row count of ``fleet_enriched_view``.

    Raises:
        ValueError: If ``view_count`` is 0.
    """
    if view_count == 0:
        raise ValueError(
            "Gold DQ FAILED: fleet_enriched_view has 0 rows. "
            "Verify that both Silver tables contain records with overlapping event_timestamp "
            "ranges within the 60-second join window."
        )
