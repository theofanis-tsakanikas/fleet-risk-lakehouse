"""Enforced Unity Catalog column masks for special-category and location data.

Classifying ``heart_rate`` / ``stress_score`` as GDPR Art. 9 data (see
:mod:`fleet_governance.classification`) documents the obligation; it does not *enforce* it.
This module closes that gap with Unity Catalog **column masks**: a SQL UDF bound to a column
that the engine applies on every read, so what a principal sees depends on their group.

Two mask policies, derived from the column classification (never a hand-kept list, so
they cannot drift from it):

* **special-category** (biometrics) — full value to the ``fleet_safety_officers`` group,
  ``NULL`` to everyone else. A safety officer acting on an alert sees the heart rate; a
  general analyst building fleet trends does not.
* **location** (lat/long) — full precision to safety officers, coarsened to ~1 decimal
  (~11 km) for everyone else, so route analytics still work without exposing a driver's
  precise position.

Coverage is *every* Gold surface that carries the classified data: ``fleet_live_status``,
``fleet_safety_alerts``, the ``fleet_live_status_quarantine`` side table (DQ-failing rows
are still raw Art. 9 biometrics), and ``driver_safety_metrics`` — per-driver aggregation
does not de-identify, so ``avg_heart_rate`` / ``avg_stress`` inherit the special-category
mask. Because a UC mask UDF's parameter type must match the column type exactly, each
policy ships typed variants (``INT`` biometrics vs. their ``DOUBLE`` aggregates).

The builders are pure (they emit the ``CREATE FUNCTION`` / ``ALTER TABLE ... SET MASK``
DDL); the Gold notebook runs them after writing each table. The masks survive
``CREATE OR REPLACE TABLE`` re-runs because the notebook re-applies them each run.
"""

from __future__ import annotations

from fleet_governance.classification import (
    LOCATION,
    SPECIAL_CATEGORY,
    ColumnClass,
    classification_index,
    metrics_classification_index,
)

# The privileged group that sees unmasked values. Override per environment.
DEFAULT_PRIVILEGED_GROUP = "fleet_safety_officers"

# Per-category mask definition: the body expression (``{group}`` and ``val`` are
# substituted) plus one UDF variant per SQL type it must bind to — a UC column mask
# requires the UDF parameter type to match the column type exactly, and the aggregate
# table carries DOUBLE aggregates of the INT biometric sources. Only classified
# categories that appear here are masked; DERIVED / OPERATIONAL / IDENTIFIER are not.
_MASKS: dict[str, dict] = {
    SPECIAL_CATEGORY: {
        "body": "CASE WHEN is_account_group_member('{group}') THEN val ELSE NULL END",
        "funcs": {"INT": "mask_biometric", "DOUBLE": "mask_biometric_double"},
    },
    LOCATION: {
        "body": "CASE WHEN is_account_group_member('{group}') THEN val ELSE ROUND(val, 1) END",
        "funcs": {"DOUBLE": "mask_location"},
    },
}


def _maskable_index() -> dict[str, ColumnClass]:
    """Every classified column across the Gold contracts (enriched view + aggregates).

    The quarantine side table shares the enriched contract's columns, so it needs no
    classification of its own — masking it reuses the same entries.
    """
    merged = dict(classification_index())
    merged.update(metrics_classification_index())
    return merged


def function_name(function_schema: str, category: str, sql_type: str = "INT") -> str:
    """Fully-qualified UDF name for a category's mask variant matching ``sql_type``.

    Raises:
        KeyError: If the category has no mask variant for ``sql_type`` — a masked
            column with an unmaskable type is a governance bug and must fail loudly.
    """
    return f"{function_schema}.{_MASKS[category]['funcs'][sql_type]}"


def masked_columns() -> tuple[str, ...]:
    """All columns that get a mask, from the classification (enriched + aggregates).

    Special-category and location columns, plus the aggregates that inherit those
    categories (``avg_heart_rate`` / ``avg_stress``) — never a hand-kept list.
    """
    return tuple(col for col, c in _maskable_index().items() if c.category in _MASKS)


def drop_mask_ddls(table: str, table_columns: list[str]) -> list[str]:
    """``ALTER TABLE ... DROP MASK`` for each masked column present in ``table``.

    Idempotency helper: a column mask is metadata bound to the column and survives a data
    overwrite / ``CREATE OR REPLACE TABLE``, so re-running :func:`apply_mask_ddls` on an
    already-masked column raises. Run these *first* — swallowing the "no mask set" error for
    a column that isn't masked yet — so re-applying the mask each run is safe.
    """
    present = set(table_columns)
    return [f"ALTER TABLE {table} ALTER COLUMN {col} DROP MASK" for col in masked_columns() if col in present]


def mask_function_ddls(function_schema: str, privileged_group: str = DEFAULT_PRIVILEGED_GROUP) -> list[str]:
    """``CREATE OR REPLACE FUNCTION`` statements for every mask variant, in ``function_schema``."""
    ddls = []
    for spec in _MASKS.values():
        body = spec["body"].format(group=privileged_group)
        for sql_type, func in spec["funcs"].items():
            ddls.append(f"CREATE OR REPLACE FUNCTION {function_schema}.{func}(val {sql_type})\nRETURN {body}")
    return ddls


def apply_mask_ddls(
    table: str,
    table_columns: list[str],
    function_schema: str,
    privileged_group: str = DEFAULT_PRIVILEGED_GROUP,
) -> list[str]:
    """``ALTER TABLE ... SET MASK`` for each masked column present in ``table``.

    Args:
        table: The target table identifier.
        table_columns: The columns the table actually has (a mask is only applied to a
            column the table contains — ``fleet_safety_alerts`` has no lat/long, so it gets
            only the biometric mask; the quarantine table shares the live contract and the
            aggregate table brings ``avg_heart_rate`` / ``avg_stress`` into scope).
        function_schema: Schema holding the mask UDFs (see :func:`mask_function_ddls`).
        privileged_group: Unused in the ALTER itself (the group is baked into the UDF); kept
            for signature symmetry with :func:`mask_function_ddls`.

    Returns:
        One ``ALTER TABLE`` statement per masked column present, in classification order.
        The UDF variant is chosen by the column's classified SQL type — a masked column
        whose type has no variant raises ``KeyError`` (fail loudly, never skip silently).
    """
    idx = _maskable_index()
    present = set(table_columns)
    ddls = []
    for col in masked_columns():
        if col not in present:
            continue
        func = function_name(function_schema, idx[col].category, idx[col].sql_type)
        ddls.append(f"ALTER TABLE {table} ALTER COLUMN {col} SET MASK {func}")
    return ddls
