"""Column-level data classification for the Gold enriched view.

This pipeline correlates vehicle telemetry with **driver biometrics** (heart rate, stress)
— special-category personal data under GDPR Art. 9. Treating it carelessly is the honest
weak point of a "fleet analytics" demo; classifying it explicitly, at the data layer, is
the trust-layer move.

Every column the Gold view emits is tagged with a data category and (for personal data) a
GDPR note and retention. The classification is the single source of truth for the generated
GDPR Art. 30 processing record and the data dictionary, and is checked against the live
schema by test — so adding an unclassified column to the Gold view fails CI.
"""

from __future__ import annotations

from dataclasses import dataclass

# Data categories (coarsest-grained governance label).
IDENTIFIER = "identifier"  # identifies a person or a tracked asset
SPECIAL_CATEGORY = "special_category"  # GDPR Art. 9 — health / biometric
LOCATION = "location"  # whereabouts of an identified driver (personal data)
OPERATIONAL = "operational"  # vehicle telemetry, not personal on its own
DERIVED = "derived"  # computed score / explanation (no new raw personal data)

# Categories that are personal data (drive the Art. 30 record).
PERSONAL_CATEGORIES = frozenset({IDENTIFIER, SPECIAL_CATEGORY, LOCATION})


@dataclass(frozen=True)
class ColumnClass:
    """Governance classification of one Gold column."""

    column: str
    category: str
    description: str
    retention: str = ""  # retention for personal-data columns
    gdpr_note: str = ""
    sql_type: str = ""  # Spark SQL type — lets the mask builders pick a type-correct UDF

    @property
    def is_personal(self) -> bool:
        return self.category in PERSONAL_CATEGORIES

    @property
    def is_special_category(self) -> bool:
        return self.category == SPECIAL_CATEGORY


# The classification of the enriched Gold view (the column contract).
COLUMN_CLASSES: tuple[ColumnClass, ...] = (
    ColumnClass(
        "driver_id",
        IDENTIFIER,
        "Pseudonymised driver identifier (no name / direct identifier).",
        retention="Operational + 90 days",
        gdpr_note="Indirect identifier; pseudonymised at source (no PII in the lakehouse).",
        sql_type="STRING",
    ),
    ColumnClass("truck_id", IDENTIFIER, "Vehicle identifier.", retention="Operational + 90 days", sql_type="STRING"),
    ColumnClass("timestamp", OPERATIONAL, "Event time of the correlated reading.", sql_type="TIMESTAMP"),
    ColumnClass(
        "latitude",
        LOCATION,
        "Vehicle latitude at the reading.",
        retention="30 days (then aggregated)",
        gdpr_note="Location of an identified driver — personal data; minimise retention.",
        sql_type="DOUBLE",
    ),
    ColumnClass(
        "longitude",
        LOCATION,
        "Vehicle longitude at the reading.",
        retention="30 days (then aggregated)",
        gdpr_note="Location of an identified driver — personal data; minimise retention.",
        sql_type="DOUBLE",
    ),
    ColumnClass("speed", OPERATIONAL, "Vehicle speed (km/h).", sql_type="INT"),
    ColumnClass("fuel_level", OPERATIONAL, "Vehicle fuel level.", sql_type="INT"),
    ColumnClass(
        "heart_rate",
        SPECIAL_CATEGORY,
        "Driver heart rate (bpm) from the wearable.",
        retention="30 days",
        gdpr_note="Health data (GDPR Art. 9) — processed for driver safety with explicit safeguards.",
        sql_type="INT",
    ),
    ColumnClass(
        "stress_score",
        SPECIAL_CATEGORY,
        "Driver stress score from the wearable.",
        retention="30 days",
        gdpr_note="Health-derived data (GDPR Art. 9) — processed for driver safety with safeguards.",
        sql_type="INT",
    ),
    ColumnClass("risk_score", DERIVED, "Composite driver risk index (0–100).", sql_type="DOUBLE"),
    ColumnClass("risk_speed_pts", DERIVED, "Risk points contributed by speed (explainability).", sql_type="DOUBLE"),
    ColumnClass("risk_stress_pts", DERIVED, "Risk points contributed by stress (explainability).", sql_type="DOUBLE"),
    ColumnClass(
        "risk_heart_rate_pts", DERIVED, "Risk points contributed by heart rate (explainability).", sql_type="DOUBLE"
    ),
    ColumnClass("risk_primary_factor", DERIVED, "The factor that drove the risk score.", sql_type="STRING"),
)

# The columns the enriched Gold view is expected to emit (the contract a test locks).
GOLD_COLUMNS: tuple[str, ...] = tuple(c.column for c in COLUMN_CLASSES)


def classification_index() -> dict[str, ColumnClass]:
    return {c.column: c for c in COLUMN_CLASSES}


# --------------------------------------------------------------------------- #
# driver_safety_metrics (the aggregate Gold table)
# --------------------------------------------------------------------------- #
# Aggregation does NOT de-identify: an hourly average heart rate keyed by driver_id
# is still the health data of one identified driver (GDPR Art. 9). Each aggregate
# therefore inherits its source column's category — derived here from the enriched
# classification, never hand-tagged, so the two tables can't drift apart.

# (aggregate column, source column, sql type, description)
_METRIC_AGGREGATES: tuple[tuple[str, str, str, str], ...] = (
    ("avg_heart_rate", "heart_rate", "DOUBLE", "Hourly average driver heart rate (bpm)."),
    ("max_speed", "speed", "INT", "Hourly maximum vehicle speed (km/h)."),
    ("avg_stress", "stress_score", "DOUBLE", "Hourly average driver stress score."),
    ("avg_risk_score", "risk_score", "DOUBLE", "Hourly average composite risk score."),
    ("max_risk_score", "risk_score", "DOUBLE", "Hourly maximum composite risk score."),
)


def _aggregate_class(column: str, source: str, sql_type: str, description: str) -> ColumnClass:
    src = classification_index()[source]
    note = src.gdpr_note
    if src.is_personal:
        note = f"Aggregate of `{source}` — per-driver aggregation does not de-identify; inherits its handling."
    return ColumnClass(column, src.category, description, retention=src.retention, gdpr_note=note, sql_type=sql_type)


# The classification of the driver_safety_metrics table (the aggregate contract).
METRICS_COLUMN_CLASSES: tuple[ColumnClass, ...] = (
    classification_index()["driver_id"],
    ColumnClass("hour_bucket", OPERATIONAL, "Start of the hourly aggregation window.", sql_type="TIMESTAMP"),
    *(_aggregate_class(*spec) for spec in _METRIC_AGGREGATES),
)

METRICS_COLUMNS: tuple[str, ...] = tuple(c.column for c in METRICS_COLUMN_CLASSES)


def metrics_classification_index() -> dict[str, ColumnClass]:
    return {c.column: c for c in METRICS_COLUMN_CLASSES}


def validate_metrics_classification(actual_columns: list[str]) -> list[str]:
    """Return governance errors comparing the live metrics columns to the classification.

    Same contract as :func:`validate_classification`, for ``driver_safety_metrics``.
    """
    classified = set(metrics_classification_index())
    actual = set(actual_columns)
    errors = []
    for col in sorted(actual - classified):
        errors.append(f"unclassified driver_safety_metrics column: {col!r} (add it to _METRIC_AGGREGATES)")
    for col in sorted(classified - actual):
        errors.append(f"classified column no longer in driver_safety_metrics: {col!r}")
    return errors


def special_category_columns() -> tuple[str, ...]:
    return tuple(c.column for c in COLUMN_CLASSES if c.is_special_category)


def personal_columns() -> tuple[str, ...]:
    return tuple(c.column for c in COLUMN_CLASSES if c.is_personal)


def validate_classification(actual_columns: list[str]) -> list[str]:
    """Return governance errors comparing the live Gold columns to the classification.

    Flags any live column with no classification (governance gap) and any classified
    column no longer produced (stale). An empty list means the classification is exactly
    in sync with the pipeline output.
    """
    classified = set(classification_index())
    actual = set(actual_columns)
    errors = []
    for col in sorted(actual - classified):
        errors.append(f"unclassified Gold column: {col!r} (add it to COLUMN_CLASSES)")
    for col in sorted(classified - actual):
        errors.append(f"classified column no longer in the Gold view: {col!r}")
    return errors
