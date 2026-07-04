# ADR-007: Enforced Unity Catalog Column Masks for Special-Category Data

**Date:** 2026-06  
**Status:** Accepted

---

## Context

The platform classifies `heart_rate` and `stress_score` as GDPR Art. 9 special-category
(health) data and `latitude` / `longitude` as location data, with a CI test that fails if any
Gold column is left unclassified (see `fleet_governance.classification` and the generated
[Data Processing Record](../governance/DATA_PROCESSING_RECORD.md)).

That classification *documents* the obligation. It does not *enforce* it. As built, any
principal with `SELECT` on the Gold tables could read raw biometrics and precise location. For
a control to be credible to a reviewer (or a DPO), the boundary between "documented as
sensitive" and "actually restricted on read" has to be closed in the platform, not in a policy
PDF.

Unity Catalog provides **column masks**: a SQL UDF bound to a column that the engine applies on
every read, returning a value that depends on the querying principal's group membership
(`is_account_group_member(...)`). This is the native, enforced mechanism.

## Decision

Apply UC **column masks** to the classified sensitive columns, derived directly from the
column classification so the masked set cannot drift from it (`fleet_governance.masking`):

- **Special-category (biometrics):** full value for the `fleet_safety_officers` group; `NULL`
  for everyone else. A safety officer acting on an alert sees the heart rate; a general analyst
  building fleet trends does not.
- **Location (lat/long):** full precision for safety officers; coarsened to ~1 decimal (~11 km)
  for everyone else — route-level analytics still work without exposing a driver's exact
  position.

The mask UDFs and `ALTER TABLE ... SET MASK` statements are produced by pure builders and
applied by the Gold notebook after each table is written. Because Gold uses
`CREATE OR REPLACE TABLE` ([ADR-004](ADR-004-micro-batch-execution.md)), any prior mask is
dropped with the table and re-applied each run — idempotent by construction. The privileged
group is a bundle variable (`mask_privileged_group`), so it is environment-configurable. The
generated Data Processing Record lists the masked columns and the privileged group, rendered
from the same classification, so the compliance doc and the enforcement cannot disagree.

Coverage is **every Gold surface that carries the classified data**, not just the headline
tables:

- `fleet_live_status` and `fleet_safety_alerts` (the original scope);
- `fleet_live_status_quarantine` — rows that fail a data-quality expectation are still raw
  Art. 9 biometrics; a side table with weaker protection than the table it quarantines *from*
  would be a governance hole, so the quarantine inherits the live table's masks;
- `driver_safety_metrics` — per-driver aggregation does **not** de-identify: an hourly
  average heart rate keyed by `driver_id` is still one identified driver's health data, so
  `avg_heart_rate` / `avg_stress` inherit the special-category mask from their source
  columns (`fleet_governance.classification.METRICS_COLUMN_CLASSES`, derived in code).

Because a UC mask UDF's parameter type must exactly match the column type, each mask policy
ships typed variants (`mask_biometric` for the INT sources, `mask_biometric_double` for
their DOUBLE aggregates); the builder selects the variant from the column's classified SQL
type and fails loudly on a masked column with no matching variant.

## Consequences

**Benefits**

- The Art. 9 control moves from *documented* to *enforced at the engine*: read access to
  biometrics is gated by group, not by convention.
- The masked set is derived from the classification, so adding a sensitive column and
  classifying it automatically brings it into scope — there is no second list to maintain.
- Location remains useful (coarsened) for analytics while precise position is restricted.

**Trade-offs**

- The masks bind to a **group** (`fleet_safety_officers`) that must exist and be governed at
  the account level; provisioning the group + its **human** members is an account-admin
  responsibility (the default name is a placeholder to confirm per deployment). The group must
  exist **before** the deploy: the account layer (`01_infra`) looks it up via a data source and
  adds the **project SPN** to it automatically, so the pipeline's own observability reads
  (biometric null-rates) are not masked. That makes it a hard dependency — a missing group fails
  the apply loudly rather than silently degrading a metric.
- Masking applies on read at the Gold tables; raw Bronze/Silver still hold unmasked values and
  rely on schema-level grants. Tightening Silver access (or masking there too) is a follow-up
  if the threat model requires it.
- Column masks are a Unity Catalog feature; the masking step is a no-op-by-omission only if UC
  is unavailable, which this platform always assumes.
