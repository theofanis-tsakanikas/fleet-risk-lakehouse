# ADR-006: SCD Type 2 Driver Dimension for Assignment History

**Date:** 2026-06  
**Status:** Accepted

---

## Context

`driver_id` and `truck_id` are carried as flat attributes on every tracker event and flow
through to the Gold tables. That captures the *current* assignment but discards its
**history**: there is no way to answer "which truck was DRV_03 driving last Tuesday?" or to
attribute a past incident to the vehicle in use at the time. Driver-to-truck reassignment is
a real, slow-moving business fact, and a fleet-safety platform that cannot reconstruct it as
of a past date is missing a basic analytical capability.

Two design questions:

1. **Where does the history live?** Folding a `driver_name` / assignment column into the Gold
   *enriched view* would change its column contract — which is deliberately locked by the
   governance classification and a CI test (an unclassified column fails the build). We do not
   want every dimensional attribute to become a governed Gold column.
2. **How is the history modelled?** Overwriting (SCD Type 1) loses exactly what we want.
   Versioned rows with validity intervals (SCD Type 2) is the standard answer.

## Decision

Add a standalone **SCD Type 2 conformed dimension**, `dim_driver`, in the Gold catalog —
*not* a change to the enriched view. Each `(driver_id, truck_id)` assignment is a versioned
row with `valid_from` / `valid_to` and an `is_current` flag; a reassignment **closes** the
open version (`valid_to = effective_ts`, `is_current = false`) and **opens** a new one. History
is never overwritten.

Following the `risk_model` discipline of "one rule, proven in two forms":

- `fleet_transforms.dimensions.apply_scd2` is a **pure-Python reference** of the transition,
  exhaustively unit-tested (new driver, unchanged, reassignment, quiet batch, idempotent
  re-run, no mutation of closed history).
- `scd2_merge_sql` is the **Databricks Delta `MERGE`** the notebook runs, using the canonical
  two-intent staging pattern; it mirrors the reference and is structurally locked by test.
- `current_assignment_select_sql` (the source snapshot) is plain SQL and runs on any Spark, so
  it is directly tested.

A new `build_dim_driver` job task reads Silver trackers and depends only on `silver_trackers`,
so it runs in parallel with the Gold enrichment.

## Consequences

**Benefits**

- As-of-date history: `fleet_live_status` and the dashboard can join `dim_driver` on
  `is_current = true` for the live view, or on a validity interval for historical attribution.
- The enriched view's governed column contract is untouched; dimensional attributes evolve
  independently of the special-category governance surface.
- The MERGE is idempotent — re-running a batch with an unchanged snapshot produces no new
  versions (proven by `test_idempotent_rerun_produces_no_new_versions`).

**Trade-offs**

- `MERGE` is a Delta feature and cannot run on the local OSS-Spark test session, so the merge
  SQL is structurally locked rather than executed in tests; the *semantics* are covered by the
  pure-Python reference. This is the same split the risk model uses.
- A driver absent from a batch is intentionally left untouched (a quiet batch is not a
  reassignment). True end-of-employment closure would need an explicit "active drivers"
  signal, not inference from absence.
