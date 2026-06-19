# Risk Model Card — Driver Risk Index

> Generated from `fleet_transforms.risk_model` by `python -m fleet_governance.generate`. Do not edit by hand.

- **Version:** `fleet-risk-index:v1`
- **Type:** transparent linear risk index (explainable by design — **not** a learned model).
- **Output range:** 0–100 (capped).

## Why a transparent index, not a learned model

This score can cause a fleet manager to contact a driver, so every point must be explainable and auditable. A linear index of weighted, normalised factors makes the model fit on one page, removes training-data and drift risk, and lets each prediction be decomposed into the exact points each factor contributed. That decomposition is emitted with the score (see Explainability).

## Factors

| Factor | Source column | Max points (weight) | Normaliser (denominator) | Contribution |
| --- | --- | --- | --- | --- |
| `speed` | `speed` | 40 | 120 | `value / 120 × 40` |
| `stress` | `stress_score` | 35 | 100 | `value / 100 × 35` |
| `heart_rate` | `heart_rate` | 25 | 110 | `value / 110 × 25` |

`risk_score = ROUND(LEAST(100, Σ factor_contributions), 2)`; NULL sensor readings contribute 0 (`COALESCE(..., 0)`).

## Explainability columns

Alongside `risk_score`, the Gold view emits the per-factor decomposition so a high-risk driver is explained, not just flagged:

- `risk_speed_pts`, `risk_stress_pts`, `risk_heart_rate_pts` — each factor's points.
- `risk_primary_factor` — the factor with the largest contribution (`none` when all are 0).

### Worked example

speed=90, stress=50, heart_rate=80 → speed 30 + stress 17.5 + heart_rate 18.18 = **risk_score 65.68**, primary factor **speed**.

## Alert thresholds

- Overspeed: `speed > 90`
- Elevated heart rate (warning): `heart_rate > 90`
- Extreme heart rate (danger): `heart_rate > 110`

## Limitations

- The score is capped at 100; multiple maxed factors all read as 100.
- Weights/denominators are an expert-set policy, not learned from outcomes; review them against incident data before relying on absolute values.
- Inputs include special-category biometric data — see the [Data Processing Record](DATA_PROCESSING_RECORD.md).

