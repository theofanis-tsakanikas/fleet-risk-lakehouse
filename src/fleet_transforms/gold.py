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
"""


def enriched_view_select_sql(t_silver_path: str, w_silver_path: str) -> str:
    """Return the SELECT defining ``fleet_enriched_view`` (temporal join + risk).

    Implements the ±60-second ``INNER JOIN`` between trackers and watches and the
    weighted ``risk_score`` (speed 40 / stress 35 / heart_rate 25, NULLs coalesced
    to 0, capped at 100 via ``LEAST``).

    Args:
        t_silver_path: Trackers Silver table identifier (aliased ``t``).
        w_silver_path: Watches Silver table identifier (aliased ``w``).

    Returns:
        The SQL ``SELECT`` body (no surrounding DDL).
    """
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
    ROUND(
        LEAST(100.0,
            (COALESCE(t.speed, 0)        / 120.0 * 40) +
            (COALESCE(w.stress_score, 0) / 100.0 * 35) +
            (COALESCE(w.heart_rate, 0)   / 110.0 * 25)
        ), 2
    ) AS risk_score
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

    Keeps every qualifying row (``speed > 90 OR heart_rate > 90``) — no per-driver
    deduplication — and classifies each into an ``alert_type``.

    Args:
        source: The enriched-view identifier to read from.

    Returns:
        The SQL ``SELECT`` body (no surrounding DDL).
    """
    return f"""
SELECT
    timestamp,
    driver_id,
    truck_id,
    speed,
    heart_rate,
    stress_score,
    risk_score,
    CASE
        WHEN speed > 90 AND heart_rate > 90 THEN 'CRITICAL: High Speed & Stress'
        WHEN heart_rate > 110 THEN 'DANGER: Extreme Heart Rate'
        WHEN heart_rate > 90 THEN 'WARNING: Elevated Heart Rate'
        WHEN speed > 90 THEN 'OVERSPEED'
        ELSE 'NORMAL'
    END as alert_type
FROM {source}
WHERE speed > 90 OR heart_rate > 90
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
