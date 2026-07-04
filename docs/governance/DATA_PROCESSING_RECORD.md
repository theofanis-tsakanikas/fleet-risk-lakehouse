# Record of Processing Activities (GDPR Art. 30)

> Generated from `fleet_governance.classification` by `python -m fleet_governance.generate`. Do not edit by hand.

## Processing activity

- **Purpose:** real-time driver safety risk monitoring for a logistics fleet.
- **Controller / DPO:** _(fill in for the deploying organisation)_.
- **Categories of data subjects:** fleet drivers.
- **Recipients:** fleet operations managers — via the Grafana safety dashboards and push notifications to Slack / PagerDuty. External notifications carry only operational and derived fields (driver/truck id, speed, risk score, alert type); **special-category biometrics are never sent to an external service** (see ADR-009).
- **International transfers:** none by default (single-region lakehouse).

## Special-category data (GDPR Art. 9)

This activity processes **2** special-category (health) fields: `heart_rate`, `stress_score`.

- **Condition for processing:** driver safety / vital-interest monitoring, with explicit safeguards (below). Confirm the lawful basis and any consent requirements for your jurisdiction.
- **Safeguards:** identifiers are pseudonymised at source (no PII in the lakehouse); biometric fields are retained 30 days then dropped from raw form; access is restricted to the operations group; **Unity Catalog column masks are enforced** on these fields (see below); the derived risk score is explainable so decisions are contestable.

## Categories of personal data

| Column | Category | GDPR note | Retention |
| --- | --- | --- | --- |
| `driver_id` | identifier | Indirect identifier; pseudonymised at source (no PII in the lakehouse). | Operational + 90 days |
| `truck_id` | identifier | — | Operational + 90 days |
| `latitude` | location | Location of an identified driver — personal data; minimise retention. | 30 days (then aggregated) |
| `longitude` | location | Location of an identified driver — personal data; minimise retention. | 30 days (then aggregated) |
| `heart_rate` | special_category | Health data (GDPR Art. 9) — processed for driver safety with explicit safeguards. | 30 days |
| `stress_score` | special_category | Health-derived data (GDPR Art. 9) — processed for driver safety with safeguards. | 30 days |

## Security & minimisation measures

- Pseudonymised `driver_id` (no names / direct identifiers in the platform).
- Least-privilege Unity Catalog grants; location data minimised to 30 days.
- Special-category columns are tagged `special_category` and enforced by a CI check that every Gold column is classified.
- **Enforced column masking** (Unity Catalog): `latitude`, `longitude`, `heart_rate`, `stress_score`, `avg_heart_rate`, `avg_stress` are masked on read — full values only for the `fleet_safety_officers` group, redacted (biometrics) or coarsened to ~11 km (location) for everyone else. The masked set is derived from this classification, so it cannot drift from it. Masks cover every Gold surface carrying the classified data: the live table, the alerts log, the data-quality quarantine side table, and the per-driver aggregates.

## Data dictionary (all Gold columns)

| Column | Category | Description | Retention |
| --- | --- | --- | --- |
| `driver_id` | identifier | Pseudonymised driver identifier (no name / direct identifier). | Operational + 90 days |
| `truck_id` | identifier | Vehicle identifier. | Operational + 90 days |
| `timestamp` | operational | Event time of the correlated reading. | — |
| `latitude` | location | Vehicle latitude at the reading. | 30 days (then aggregated) |
| `longitude` | location | Vehicle longitude at the reading. | 30 days (then aggregated) |
| `speed` | operational | Vehicle speed (km/h). | — |
| `fuel_level` | operational | Vehicle fuel level. | — |
| `heart_rate` | special_category | Driver heart rate (bpm) from the wearable. | 30 days |
| `stress_score` | special_category | Driver stress score from the wearable. | 30 days |
| `risk_score` | derived | Composite driver risk index (0–100). | — |
| `risk_speed_pts` | derived | Risk points contributed by speed (explainability). | — |
| `risk_stress_pts` | derived | Risk points contributed by stress (explainability). | — |
| `risk_heart_rate_pts` | derived | Risk points contributed by heart rate (explainability). | — |
| `risk_primary_factor` | derived | The factor that drove the risk score. | — |

## Aggregate table (`driver_safety_metrics`)

Per-driver aggregation does **not** de-identify: an hourly average heart rate keyed by `driver_id` is still the health data of one identified driver (GDPR Art. 9). Each aggregate column therefore inherits its source column's category and handling — derived in code, never hand-tagged:

| Column | Category | Description | Retention |
| --- | --- | --- | --- |
| `driver_id` | identifier | Pseudonymised driver identifier (no name / direct identifier). | Operational + 90 days |
| `hour_bucket` | operational | Start of the hourly aggregation window. | — |
| `avg_heart_rate` | special_category | Hourly average driver heart rate (bpm). | 30 days |
| `max_speed` | operational | Hourly maximum vehicle speed (km/h). | — |
| `avg_stress` | special_category | Hourly average driver stress score. | 30 days |
| `avg_risk_score` | derived | Hourly average composite risk score. | — |
| `max_risk_score` | derived | Hourly maximum composite risk score. | — |

