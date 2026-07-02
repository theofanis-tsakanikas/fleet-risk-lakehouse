# ADR-005: Declarative Data-Quality Expectations with Quarantine

**Date:** 2026-06  
**Status:** Accepted

---

## Context

The Gold notebook originally guarded itself with hand-rolled checks inlined in the notebook:

```python
null_keys = spark.sql(f"SELECT COUNT(*) ... WHERE driver_id IS NULL ...").collect()[0]["cnt"]
if null_keys > 0:
    raise ValueError(...)
```

This works, but it has three weaknesses a reviewer notices immediately:

1. **It conflates detection with reaction.** The only response to bad data is to crash the
   whole run — there is no way to keep the good rows and set the bad ones aside.
2. **The rules are scattered and imperative.** Each check is a bespoke SQL string plus an
   `if`, buried in the notebook, untestable in isolation.
3. **It loses the evidence.** "The run failed" is all you get; not *which* rows, *why*, or
   *how many*.

Tools like Great Expectations, Soda, and Delta Live Tables `EXPECT` exist precisely for this.
Adopting one wholesale, however, adds a dependency and (for GE/Soda) a config surface and
runtime that is heavy for a project whose whole DQ surface is a handful of rules.

## Decision

Introduce a tiny **declarative expectation framework** in `fleet_transforms.quality` (no new
dependencies, fully unit-tested on local Spark) modelled on the same concepts as DLT `EXPECT`:

- An **`Expectation`** is a *named boolean SQL predicate every valid row must satisfy*, with a
  **`Severity`** (`ERROR` quarantines + can fail the run; `WARN` records only).
- **`evaluate`** counts violations per expectation; **`split`** divides a DataFrame into
  `(valid, quarantine)` where the quarantine rows are annotated with a `_dq_failures` array
  naming the expectations they broke; **`enforce`** raises only if an `ERROR` expectation was
  violated.

The Gold `fleet_live_status` suite is built from `RISK_MODEL` (e.g. `risk_score BETWEEN 0 AND
cap`), so the checks cannot drift from the formula. Violating rows are written to a
`*_quarantine` side table instead of being silently dropped or crashing the run blind.

Predicates are kept as **SQL strings** so the exact same rule could later be pushed into a
Delta `CHECK` constraint or a DLT `EXPECT` without translation.

## Consequences

**Benefits**

- Bad data is *captured and explained* (which rule, how many rows, which rows), not just
  fatal. Operators get a quarantine table to triage.
- The rules are declarative, centralised, and unit-tested independently of any cluster.
- `WARN` vs `ERROR` lets soft signals (e.g. a missing `risk_primary_factor`) be recorded
  without blocking the pipeline, while hard invariants still fail it.

**Trade-offs**

- It is a deliberately small framework, not a feature-complete DQ platform — no historical
  metric store or anomaly detection beyond what `pipeline_metrics` and the drift check
  provide. That is the right scope here; if the rule set grows substantially, revisit DLT
  `EXPECT` (native, since Gold already runs on Databricks) before growing this module.
- Each expectation is a separate count pass. Fine at this data scale; batch them if the suite
  grows large (see the [scaling notes](../SCALING.md)).
