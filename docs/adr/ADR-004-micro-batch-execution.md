# ADR-004: Micro-Batch Execution for the Gold Layer (not Continuous Streaming)

**Date:** 2026-06  
**Status:** Accepted

---

## Context

Bronze and Silver are Spark Structured Streaming jobs (Auto Loader → Delta). A reasonable
question for a "real-time" platform is why the Gold layer — the temporal join, risk scoring,
and the three business tables — is recomputed in a batch step (`trigger(availableNow=True)`
upstream, full `CREATE OR REPLACE TABLE` at Gold) rather than run as a continuously-executing
stream with `trigger(processingTime=...)` or Continuous Processing mode.

The pull toward continuous execution is the "real-time" label. The pull away from it is that
the Gold layer's core operation is a **stream–stream temporal join with a ±60s symmetric
window** (see [ADR-002](ADR-002-temporal-join-window.md)) feeding **stateful aggregations**
(hourly `window()` buckets) and a **`ROW_NUMBER` dedup**. Running those continuously commits
the pipeline to managing join state and watermarks indefinitely, late-data semantics, and an
always-on cluster — real operational cost and complexity.

## Decision

Run Bronze/Silver as incremental streams with `availableNow` triggers and Gold as a
**scheduled micro-batch recompute**. The job is triggered on demand / on a schedule; each run
processes all newly-arrived files and rebuilds the Gold tables, then the cluster releases.

The serverless SQL Warehouse that serves Grafana ([ADR-003](ADR-003-sql-warehouse-grafana.md))
gives the dashboards their "live" feel via fast warm queries over the freshly-written Gold
tables — the freshness the use case needs (a fleet manager acting within minutes) is met by
the run cadence, not by sub-second streaming.

## Consequences

**Benefits**

- No long-lived join/aggregation state to manage, no watermark tuning, no continuous cluster
  cost. The pipeline is cheap to run and trivial to reason about: each run is a pure function
  of the files present.
- Idempotent, debuggable runs. A failed run leaves no partial streaming state; re-running
  reprocesses cleanly. The empty-view DQ guard and the quarantine flow
  ([ADR-005](ADR-005-declarative-data-quality.md)) assume a discrete run boundary.
- The SCD2 dimension ([ADR-006](ADR-006-scd2-driver-dimension.md)) and the drift / pipeline
  metrics are naturally per-run concepts that fit a batch boundary.

**Trade-offs**

- End-to-end latency is the run interval (minutes), not seconds. For driver-safety escalation
  this is acceptable; for a hard sub-second SLA it would not be, and Gold would need to move
  to a stateful stream-stream join with watermarks.
- "Real-time" is therefore *near*-real-time. The README and dashboards should not overstate
  this.

**When to revisit**

If the freshness requirement tightens below the run interval, migrate Gold to a continuously-
triggered stream-stream join with an explicit watermark (≥ the 60s window) and convert the
`CREATE OR REPLACE TABLE` writes to streaming upserts (`foreachBatch` + Delta `MERGE`). The
pure SQL builders in `fleet_transforms.gold` are deliberately stateless and would port to a
`foreachBatch` body with minimal change — the join and risk logic do not need to be rewritten.
