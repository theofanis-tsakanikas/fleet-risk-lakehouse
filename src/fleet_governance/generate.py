"""Generate the Fleet governance documentation from code.

Two artifacts, both rendered deterministically from the single sources of truth (the risk
model + the column classification), so they can never drift from the pipeline:

* ``docs/governance/RISK_MODEL_CARD.md`` — the risk index: factors, weights, normalisation,
  cap, the explainability columns, alert thresholds, a worked example, and limitations. The
  card is honest that this is a *transparent linear index*, not a learned model — a
  deliberate, auditable choice for a score that escalates a human.
* ``docs/governance/DATA_PROCESSING_RECORD.md`` — a GDPR Article 30 record of processing
  for the driver-biometric data plus the column-level data dictionary, generated from the
  classification (special-category heart-rate / stress handling made explicit).

CI asserts the committed docs match a fresh render (``--check``).

Run: ``PYTHONPATH=src python -m fleet_governance.generate`` (or ``make govern-docs``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fleet_governance.classification import (
    COLUMN_CLASSES,
    METRICS_COLUMN_CLASSES,
    SPECIAL_CATEGORY,
    classification_index,
    personal_columns,
    special_category_columns,
)
from fleet_governance.masking import DEFAULT_PRIVILEGED_GROUP, masked_columns
from fleet_transforms.risk_model import RISK_MODEL

DOCS = Path("docs/governance")


def render_risk_model_card() -> str:
    m = RISK_MODEL
    factor_rows = [
        f"| `{f.name}` | `{f.source_column}` | {f.weight:g} | {f.denominator:g} | "
        f"`value / {f.denominator:g} × {f.weight:g}` |"
        for f in m.factors
    ]
    # A worked example tying the formula to the explainability columns.
    example = {"speed": 90, "stress_score": 50, "heart_rate": 80}
    contribs = m.contributions(example)
    out = [
        "# Risk Model Card — Driver Risk Index",
        "",
        "> Generated from `fleet_transforms.risk_model` by `python -m fleet_governance.generate`. "
        "Do not edit by hand.",
        "",
        f"- **Version:** `{m.version}`",
        "- **Type:** transparent linear risk index (explainable by design — **not** a learned model).",
        "- **Output range:** 0–100 (capped).",
        "",
        "## Why a transparent index, not a learned model",
        "",
        "This score can cause a fleet manager to contact a driver, so every point must be "
        "explainable and auditable. A linear index of weighted, normalised factors makes the "
        "model fit on one page, removes training-data and drift risk, and lets each prediction be "
        "decomposed into the exact points each factor contributed. That decomposition is emitted "
        "with the score (see Explainability).",
        "",
        "## Factors",
        "",
        "| Factor | Source column | Max points (weight) | Normaliser (denominator) | Contribution |",
        "| --- | --- | --- | --- | --- |",
        *factor_rows,
        "",
        f"`risk_score = ROUND(LEAST({m.cap:g}, Σ factor_contributions), 2)`; NULL sensor readings "
        "contribute 0 (`COALESCE(..., 0)`).",
        "",
        "## Explainability columns",
        "",
        "Alongside `risk_score`, the Gold view emits the per-factor decomposition so a high-risk "
        "driver is explained, not just flagged:",
        "",
        "- `risk_speed_pts`, `risk_stress_pts`, `risk_heart_rate_pts` — each factor's points.",
        "- `risk_primary_factor` — the factor with the largest contribution (`none` when all are 0).",
        "",
        "### Worked example",
        "",
        f"speed=90, stress=50, heart_rate=80 → "
        f"speed {contribs['speed']:g} + stress {contribs['stress']:g} + heart_rate "
        f"{contribs['heart_rate']:g} = **risk_score {m.score(example):g}**, "
        f"primary factor **{m.primary_factor(example)}**.",
        "",
        "## Alert thresholds",
        "",
        f"- Overspeed: `speed > {m.overspeed}`",
        f"- Elevated heart rate (warning): `heart_rate > {m.heart_rate_warning}`",
        f"- Extreme heart rate (danger): `heart_rate > {m.heart_rate_danger}`",
        "",
        "## Limitations",
        "",
        f"- The score is capped at {m.cap:g}; multiple maxed factors all read as {m.cap:g}.",
        "- Weights/denominators are an expert-set policy, not learned from outcomes; review them "
        "against incident data before relying on absolute values.",
        "- Inputs include special-category biometric data — see the "
        "[Data Processing Record](DATA_PROCESSING_RECORD.md).",
        "",
    ]
    return "\n".join(out) + "\n"


def render_processing_record() -> str:
    idx = classification_index()
    special = special_category_columns()
    dict_rows = [f"| `{c.column}` | {c.category} | {c.description} | {c.retention or '—'} |" for c in COLUMN_CLASSES]
    metrics_rows = [
        f"| `{c.column}` | {c.category} | {c.description} | {c.retention or '—'} |" for c in METRICS_COLUMN_CLASSES
    ]
    personal_rows = [
        f"| `{col}` | {idx[col].category} | {idx[col].gdpr_note or '—'} | {idx[col].retention or '—'} |"
        for col in personal_columns()
    ]
    out = [
        "# Record of Processing Activities (GDPR Art. 30)",
        "",
        "> Generated from `fleet_governance.classification` by `python -m fleet_governance.generate`. "
        "Do not edit by hand.",
        "",
        "## Processing activity",
        "",
        "- **Purpose:** real-time driver safety risk monitoring for a logistics fleet.",
        "- **Controller / DPO:** _(fill in for the deploying organisation)_.",
        "- **Categories of data subjects:** fleet drivers.",
        "- **Recipients:** fleet operations managers (via the Grafana safety dashboards).",
        "- **International transfers:** none by default (single-region lakehouse).",
        "",
        "## Special-category data (GDPR Art. 9)",
        "",
        f"This activity processes **{len(special)}** special-category (health) fields: "
        f"{', '.join(f'`{c}`' for c in special)}.",
        "",
        "- **Condition for processing:** driver safety / vital-interest monitoring, with explicit "
        "safeguards (below). Confirm the lawful basis and any consent requirements for your jurisdiction.",
        "- **Safeguards:** identifiers are pseudonymised at source (no PII in the lakehouse); "
        "biometric fields are retained 30 days then dropped from raw form; access is restricted to "
        "the operations group; **Unity Catalog column masks are enforced** on these fields (see "
        "below); the derived risk score is explainable so decisions are contestable.",
        "",
        "## Categories of personal data",
        "",
        "| Column | Category | GDPR note | Retention |",
        "| --- | --- | --- | --- |",
        *personal_rows,
        "",
        "## Security & minimisation measures",
        "",
        "- Pseudonymised `driver_id` (no names / direct identifiers in the platform).",
        "- Least-privilege Unity Catalog grants; location data minimised to 30 days.",
        f"- Special-category columns are tagged `{SPECIAL_CATEGORY}` and enforced by a CI check that "
        "every Gold column is classified.",
        f"- **Enforced column masking** (Unity Catalog): {', '.join(f'`{c}`' for c in masked_columns())} "
        f"are masked on read — full values only for the `{DEFAULT_PRIVILEGED_GROUP}` group, "
        "redacted (biometrics) or coarsened to ~11 km (location) for everyone else. The masked set "
        "is derived from this classification, so it cannot drift from it. Masks cover every Gold "
        "surface carrying the classified data: the live table, the alerts log, the data-quality "
        "quarantine side table, and the per-driver aggregates.",
        "",
        "## Data dictionary (all Gold columns)",
        "",
        "| Column | Category | Description | Retention |",
        "| --- | --- | --- | --- |",
        *dict_rows,
        "",
        "## Aggregate table (`driver_safety_metrics`)",
        "",
        "Per-driver aggregation does **not** de-identify: an hourly average heart rate keyed by "
        "`driver_id` is still the health data of one identified driver (GDPR Art. 9). Each aggregate "
        "column therefore inherits its source column's category and handling — derived in code, "
        "never hand-tagged:",
        "",
        "| Column | Category | Description | Retention |",
        "| --- | --- | --- | --- |",
        *metrics_rows,
        "",
    ]
    return "\n".join(out) + "\n"


def all_artifacts(root: Path) -> dict[Path, str]:
    return {
        root / DOCS / "RISK_MODEL_CARD.md": render_risk_model_card(),
        root / DOCS / "DATA_PROCESSING_RECORD.md": render_processing_record(),
    }


def _default_root() -> Path:
    # src/fleet_governance/generate.py → repo root is three parents up.
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Fleet governance docs from code.")
    parser.add_argument("--root", default=str(_default_root()))
    parser.add_argument("--check", action="store_true", help="fail if committed docs are stale")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    artifacts = all_artifacts(root)

    if args.check:
        stale = [
            str(p.relative_to(root))
            for p, content in artifacts.items()
            if not p.is_file() or p.read_text(encoding="utf-8") != content
        ]
        if stale:
            print("STALE governance docs (run `make govern-docs`):")
            for p in stale:
                print(f"  - {p}")
            return 1
        print("governance docs are up to date.")
        return 0

    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
