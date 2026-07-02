"""Slowly-Changing-Dimension (Type 2) for the driver → truck assignment.

The pipeline treats ``driver_id`` / ``truck_id`` as flat attributes on every event, so the
*history* of who drove what is lost — you can never ask "which truck was DRV_03 assigned to
last Tuesday?". A driver changing trucks is a real, slow-moving business event, which is
exactly what an SCD Type 2 dimension is for: each assignment becomes a versioned row with a
validity interval, old versions are closed (never overwritten), and the current version is
flagged.

The Gold *enriched view* is intentionally left unchanged (its column contract is locked by
the governance classification), so ``dim_driver`` is a standalone conformed dimension in the
Gold catalog that ``fleet_live_status`` and the dashboard can join for as-of history.

Following ``risk_model``'s discipline, the SCD2 semantics exist twice and are proven equal:
a pure-Python reference (:func:`apply_scd2`, exhaustively unit-tested) and the Databricks
Delta ``MERGE`` (:func:`scd2_merge_sql`) the notebook actually runs. The current-assignment
source query (:func:`current_assignment_select_sql`) is plain SQL and runs on any Spark.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# SCD2 dimension columns (the table contract).
DIM_COLUMNS: tuple[str, ...] = ("driver_id", "truck_id", "valid_from", "valid_to", "is_current")


@dataclass(frozen=True)
class DimRecord:
    """One versioned driver→truck assignment.

    ``valid_to is None`` and ``is_current`` mark the open (live) version; closed versions
    carry the timestamp at which a reassignment ended them.
    """

    driver_id: str
    truck_id: str
    valid_from: datetime
    valid_to: datetime | None
    is_current: bool


def apply_scd2(
    existing: list[DimRecord],
    incoming: dict[str, str],
    effective_ts: datetime,
) -> list[DimRecord]:
    """The reference SCD2 transition — pure, deterministic, the semantics the MERGE mirrors.

    Args:
        existing: The current dimension contents (all versions, current and closed).
        incoming: The latest ``{driver_id: truck_id}`` snapshot from Silver.
        effective_ts: The instant a change takes effect (close-old / open-new boundary).
            Passed in (never wall-clocked) so the function is pure and testable.

    Rules:
        * New driver → open a new current version from ``effective_ts``.
        * Same truck as the current version → no change (idempotent re-runs are safe).
        * Different truck → close the current version (``valid_to = effective_ts``,
          ``is_current = False``) and open a new current version.
        * A driver absent from ``incoming`` is left untouched (a quiet batch is not a
          reassignment). Closed historical versions are never mutated.

    Returns:
        The new dimension contents, ordered by ``(driver_id, valid_from)``.
    """
    current_by_driver = {r.driver_id: r for r in existing if r.is_current}

    result: list[DimRecord] = [r for r in existing if not r.is_current]
    handled_current: set[str] = set()

    for driver_id, current in current_by_driver.items():
        new_truck = incoming.get(driver_id)
        if new_truck is None or new_truck == current.truck_id:
            # Not in this snapshot, or unchanged — keep the current version as-is.
            result.append(current)
        else:
            # Reassignment: close the old version, open a new one.
            result.append(DimRecord(driver_id, current.truck_id, current.valid_from, effective_ts, False))
            result.append(DimRecord(driver_id, new_truck, effective_ts, None, True))
        handled_current.add(driver_id)

    # Drivers seen for the first time.
    for driver_id, truck_id in incoming.items():
        if driver_id not in handled_current:
            result.append(DimRecord(driver_id, truck_id, effective_ts, None, True))

    return sorted(result, key=lambda r: (r.driver_id, r.valid_from))


def current_assignment_select_sql(silver_source: str) -> str:
    """SELECT the latest ``driver_id → truck_id`` assignment per driver from Silver trackers.

    Picks the most recent non-null assignment per driver (``ROW_NUMBER ... ORDER BY
    event_timestamp DESC``). This is the staged "updates" source the SCD2 MERGE reads from,
    and it runs on plain Spark (no Delta), so the snapshot logic is directly testable.

    Args:
        silver_source: The Silver trackers table / view identifier.

    Returns:
        The SQL ``SELECT`` body (no surrounding DDL).
    """
    return f"""
SELECT driver_id, truck_id FROM (
    SELECT driver_id, truck_id,
        ROW_NUMBER() OVER (PARTITION BY driver_id ORDER BY event_timestamp DESC) AS rn
    FROM {silver_source}
    WHERE driver_id IS NOT NULL AND truck_id IS NOT NULL
) WHERE rn = 1
"""


def create_dim_table_sql(dim_table: str) -> str:
    """``CREATE TABLE IF NOT EXISTS`` for the SCD2 dimension (Delta)."""
    return f"""
CREATE TABLE IF NOT EXISTS {dim_table} (
    driver_id STRING,
    truck_id STRING,
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    is_current BOOLEAN
) USING DELTA
"""


def scd2_merge_sql(dim_table: str, updates_view: str, effective_ts_expr: str) -> str:
    """The Databricks Delta SCD2 ``MERGE`` mirroring :func:`apply_scd2`.

    Uses the canonical two-intent staging trick: each changed/new key contributes one row
    keyed for the INSERT (``mergeKey = NULL``) and, for changed keys, one row keyed to close
    the open version. Closing sets ``valid_to`` and ``is_current = false``; opening inserts a
    fresh current version from ``effective_ts_expr``.

    Args:
        dim_table: The target ``dim_driver`` Delta table identifier.
        updates_view: A view of the current ``(driver_id, truck_id)`` snapshot
            (see :func:`current_assignment_select_sql`).
        effective_ts_expr: SQL timestamp expression for the change boundary
            (e.g. ``"current_timestamp()"`` or a bound run timestamp).
    """
    return f"""
MERGE INTO {dim_table} AS dim
USING (
    SELECT u.driver_id AS merge_key, u.driver_id, u.truck_id FROM {updates_view} u
    UNION ALL
    SELECT NULL AS merge_key, u.driver_id, u.truck_id
    FROM {updates_view} u
    JOIN {dim_table} d ON u.driver_id = d.driver_id
    WHERE d.is_current = true AND d.truck_id <> u.truck_id
) AS staged
ON dim.driver_id = staged.merge_key AND dim.is_current = true
WHEN MATCHED AND dim.truck_id <> staged.truck_id THEN
    UPDATE SET dim.is_current = false, dim.valid_to = {effective_ts_expr}
WHEN NOT MATCHED THEN
    INSERT (driver_id, truck_id, valid_from, valid_to, is_current)
    VALUES (staged.driver_id, staged.truck_id, {effective_ts_expr}, NULL, true)
"""
