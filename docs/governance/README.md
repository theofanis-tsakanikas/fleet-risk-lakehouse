# Fleet Governance

The fleet pipeline correlates vehicle telemetry with **driver biometrics** (heart rate,
stress) and turns them into a risk score that can put a fleet manager in touch with a
driver. That makes two things non-negotiable: the score must be **explainable**, and the
**special-category personal data** must be governed. This folder is where both are proven
and documented — from the code, gated in CI.

## What's here

| Concern | Code | Output |
|---|---|---|
| **Explainable risk score** | `src/fleet_transforms/risk_model.py` | The risk index is a single source of truth (weights, normalisers, cap, thresholds). The Gold view emits each factor's point contribution + `risk_primary_factor`, so a high-risk driver is *explained*, not just flagged. |
| **Biometric data classification** | `src/fleet_governance/classification.py` | Every Gold column is tagged (identifier / special-category / location / operational / derived). Heart rate + stress are flagged GDPR Art. 9. A CI test asserts the classification matches the live Gold schema — an unclassified column fails the build. |
| **Generated documentation** | `src/fleet_governance/generate.py` | [RISK_MODEL_CARD.md](RISK_MODEL_CARD.md) and [DATA_PROCESSING_RECORD.md](DATA_PROCESSING_RECORD.md), rendered from the model + classification. CI fails if they drift (`--check`). |

## Why the risk score is a transparent index, not a learned model

This is the honest, deliberate design choice. The score escalates a human, so every point
must be auditable. A linear index of weighted, normalised factors:

- fits on one page and is explainable **by construction** (no post-hoc attribution),
- has no training data, no label requirement, and no model drift,
- decomposes every prediction into the exact points each factor contributed — emitted with
  the score as `risk_speed_pts` / `risk_stress_pts` / `risk_heart_rate_pts` and
  `risk_primary_factor`.

That is the responsible choice for a safety score — and it is documented as such in the
[model card](RISK_MODEL_CARD.md), weights and limitations included.

## Generated artifacts (do not edit by hand)

- [RISK_MODEL_CARD.md](RISK_MODEL_CARD.md) — factors, weights, normalisers, cap, explainability columns, alert thresholds, a worked example, limitations.
- [DATA_PROCESSING_RECORD.md](DATA_PROCESSING_RECORD.md) — GDPR Art. 30 record of processing for the biometric data + the full data dictionary.

```bash
PYTHONPATH=src python -m fleet_governance.generate          # regenerate both docs
PYTHONPATH=src python -m fleet_governance.generate --check   # CI: fail if stale
```
