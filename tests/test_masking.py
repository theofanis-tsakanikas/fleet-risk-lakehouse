"""Tests for enforced Unity Catalog column masks.

Masks are derived from the column classification (special-category + location only), so the
set is locked against it. Covers the CREATE FUNCTION DDL, per-table ALTER targeting (only
columns present), and the privileged-group wiring.
"""

from fleet_governance.classification import special_category_columns
from fleet_governance.masking import (
    apply_mask_ddls,
    drop_mask_ddls,
    mask_function_ddls,
    masked_columns,
)

SCHEMA = "fleet_dev.operations"


def test_masked_columns_are_special_category_plus_location():
    cols = set(masked_columns())
    assert set(special_category_columns()) <= cols  # biometrics always masked
    assert {"latitude", "longitude"} <= cols
    # Derived / operational / identifier columns are never masked.
    assert "risk_score" not in cols
    assert "speed" not in cols
    assert "driver_id" not in cols


def test_mask_function_ddls_bake_in_privileged_group():
    ddls = mask_function_ddls(SCHEMA, privileged_group="fleet_safety_officers")
    blob = "\n".join(ddls)
    assert f"CREATE OR REPLACE FUNCTION {SCHEMA}.mask_biometric(val INT)" in blob
    assert f"CREATE OR REPLACE FUNCTION {SCHEMA}.mask_location(val DOUBLE)" in blob
    assert "is_account_group_member('fleet_safety_officers')" in blob
    assert "ROUND(val, 1)" in blob  # location coarsening for non-privileged


def test_apply_mask_targets_only_columns_present():
    # fleet_safety_alerts has biometrics but no lat/long.
    alerts_cols = ["timestamp", "driver_id", "heart_rate", "stress_score", "risk_score"]
    ddls = apply_mask_ddls("fleet_dev.operations.fleet_safety_alerts", alerts_cols, SCHEMA)
    masked = {d.split("ALTER COLUMN ")[1].split(" SET MASK")[0] for d in ddls}
    assert masked == {"heart_rate", "stress_score"}  # no location columns present
    assert all("SET MASK fleet_dev.operations.mask_biometric" in d for d in ddls)


def test_apply_mask_covers_location_when_present():
    live_cols = ["driver_id", "latitude", "longitude", "heart_rate", "stress_score", "risk_score"]
    ddls = apply_mask_ddls("fleet_dev.operations.fleet_live_status", live_cols, SCHEMA)
    masked = {d.split("ALTER COLUMN ")[1].split(" SET MASK")[0] for d in ddls}
    assert masked == {"latitude", "longitude", "heart_rate", "stress_score"}
    loc = [d for d in ddls if "latitude" in d][0]
    assert "SET MASK fleet_dev.operations.mask_location" in loc


def test_aggregate_biometrics_masked_with_double_variant():
    # driver_safety_metrics: DOUBLE aggregates of the INT biometric sources get the
    # type-matching UDF variant (a UC mask's parameter type must equal the column type).
    metrics_cols = [
        "driver_id",
        "hour_bucket",
        "avg_heart_rate",
        "max_speed",
        "avg_stress",
        "avg_risk_score",
        "max_risk_score",
    ]
    ddls = apply_mask_ddls("fleet_dev.operations.driver_safety_metrics", metrics_cols, SCHEMA)
    masked = {d.split("ALTER COLUMN ")[1].split(" SET MASK")[0] for d in ddls}
    assert masked == {"avg_heart_rate", "avg_stress"}  # aggregation does not de-identify
    assert all(f"SET MASK {SCHEMA}.mask_biometric_double" in d for d in ddls)
    # Non-personal aggregates stay unmasked.
    assert "max_speed" not in masked and "avg_risk_score" not in masked


def test_quarantine_table_gets_the_same_masks_as_live():
    # DQ-failing rows are still raw Art. 9 biometrics — the quarantine side table
    # (live contract + DQ annotation columns) must mask exactly what the live table does.
    live_cols = ["driver_id", "latitude", "longitude", "heart_rate", "stress_score", "risk_score"]
    quarantine_cols = [*live_cols, "_dq_failures", "_dq_run_id"]
    live = apply_mask_ddls("fleet_dev.operations.fleet_live_status", live_cols, SCHEMA)
    quarantine = apply_mask_ddls("fleet_dev.operations.fleet_live_status_quarantine", quarantine_cols, SCHEMA)

    def targets(ddls):
        return {d.split("ALTER COLUMN ")[1].split(" SET MASK")[0] for d in ddls}

    assert targets(quarantine) == targets(live)


def test_mask_function_ddls_include_typed_variants():
    ddls = mask_function_ddls(SCHEMA)
    blob = "\n".join(ddls)
    assert f"CREATE OR REPLACE FUNCTION {SCHEMA}.mask_biometric_double(val DOUBLE)" in blob


def test_drop_mask_ddls_mirror_apply_for_idempotent_reapply():
    # Re-applying a mask each run requires dropping any prior mask first; the DROP set must
    # cover exactly the same columns the SET set targets (for the columns present).
    live_cols = ["driver_id", "latitude", "longitude", "heart_rate", "stress_score", "risk_score"]
    drops = drop_mask_ddls("fleet_dev.operations.fleet_live_status", live_cols)
    dropped = {d.split("ALTER COLUMN ")[1].split(" DROP MASK")[0] for d in drops}
    assert dropped == {"latitude", "longitude", "heart_rate", "stress_score"}
    assert all(d.endswith("DROP MASK") for d in drops)
    # A table without the masked columns yields no DROPs.
    assert drop_mask_ddls("t", ["driver_id", "risk_score"]) == []
