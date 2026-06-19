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
    ),
    ColumnClass("truck_id", IDENTIFIER, "Vehicle identifier.", retention="Operational + 90 days"),
    ColumnClass("timestamp", OPERATIONAL, "Event time of the correlated reading."),
    ColumnClass(
        "latitude",
        LOCATION,
        "Vehicle latitude at the reading.",
        retention="30 days (then aggregated)",
        gdpr_note="Location of an identified driver — personal data; minimise retention.",
    ),
    ColumnClass(
        "longitude",
        LOCATION,
        "Vehicle longitude at the reading.",
        retention="30 days (then aggregated)",
        gdpr_note="Location of an identified driver — personal data; minimise retention.",
    ),
    ColumnClass("speed", OPERATIONAL, "Vehicle speed (km/h)."),
    ColumnClass("fuel_level", OPERATIONAL, "Vehicle fuel level."),
    ColumnClass(
        "heart_rate",
        SPECIAL_CATEGORY,
        "Driver heart rate (bpm) from the wearable.",
        retention="30 days",
        gdpr_note="Health data (GDPR Art. 9) — processed for driver safety with explicit safeguards.",
    ),
    ColumnClass(
        "stress_score",
        SPECIAL_CATEGORY,
        "Driver stress score from the wearable.",
        retention="30 days",
        gdpr_note="Health-derived data (GDPR Art. 9) — processed for driver safety with safeguards.",
    ),
    ColumnClass("risk_score", DERIVED, "Composite driver risk index (0–100)."),
    ColumnClass("risk_speed_pts", DERIVED, "Risk points contributed by speed (explainability)."),
    ColumnClass("risk_stress_pts", DERIVED, "Risk points contributed by stress (explainability)."),
    ColumnClass("risk_heart_rate_pts", DERIVED, "Risk points contributed by heart rate (explainability)."),
    ColumnClass("risk_primary_factor", DERIVED, "The factor that drove the risk score."),
)

# The columns the enriched Gold view is expected to emit (the contract a test locks).
GOLD_COLUMNS: tuple[str, ...] = tuple(c.column for c in COLUMN_CLASSES)


def classification_index() -> dict[str, ColumnClass]:
    return {c.column: c for c in COLUMN_CLASSES}


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
