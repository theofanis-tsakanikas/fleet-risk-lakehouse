# Scaling Notes

The pipeline is provisioned for a **dev-scale fleet of 10 drivers**: a 2X-Small serverless SQL
Warehouse, single-partition shuffles in tests, and low-cardinality Gold tables. This note
records what changes — and what does *not* — as the fleet grows toward, say, **10,000
drivers** (a ~1,000× increase in event volume). It is written so the design choices are
defensible at scale, not just at demo scale.

## What stays the same

- **The medallion shape and the pure transform logic.** The Silver cleansing rules, the risk
  model, the temporal-join SQL, the DQ expectations, and the SCD2 semantics are all
  size-independent — they are row-wise or per-key and carry no global state. None need
  rewriting.
- **The governance surface.** Classification, masking, and the generated Art. 30 record are
  per-column, not per-row.
- **Idempotency and the run model.** Micro-batch ([ADR-004](adr/ADR-004-micro-batch-execution.md))
  scales by processing more files per run; the per-run contract is unchanged.

## What must change

### 1. Storage layout — partitioning & clustering
At 10k drivers the Gold tables move from "small" to "needs a layout". Add:
- **Liquid clustering** (or `ZORDER`) on `driver_id` for `fleet_live_status` and
  `fleet_safety_alerts` (the dashboard's main filter), and on `(driver_id, hour_bucket)` for
  `driver_safety_metrics`.
- Partition the high-volume Bronze/Silver Delta tables by **ingestion date**; keep
  `OPTIMIZE` + retention (`VACUUM`) on a schedule.

### 2. The temporal join
The ±60s stream-stream join is the most size-sensitive operation. At scale:
- Ensure both Silver inputs are clustered on `driver_id` so the join is co-partitioned and
  avoids a wide shuffle.
- If skew appears (a few very chatty devices), salt the join key or cap per-driver events per
  window. The window itself (60s) is a correctness parameter, not a performance knob — tune it
  against real device frequency ([ADR-002](adr/ADR-002-temporal-join-window.md)), not load.

### 3. Compute sizing
- SQL Warehouse: step the size up (Small → Medium) and raise the max-cluster count for
  concurrent Grafana refreshes; auto-stop stays the cost guard.
- Job compute: the environment scales horizontally; the bottleneck is the join shuffle, which
  the clustering above addresses.

### 4. Data-quality cost
Each expectation is currently a separate count pass ([ADR-005](adr/ADR-005-declarative-data-quality.md)).
At 10k drivers, fold the suite into a **single pass** (one aggregation computing all violation
counts) or push the predicates into Delta `CHECK` constraints / DLT `EXPECT`. The
`Expectation` predicates are already SQL strings precisely so this is a mechanical change.

### 5. Latency vs. freshness
If minutes-scale freshness stops being enough at scale, that is the trigger to migrate Gold to
a continuously-triggered stateful stream-stream join (the migration path is documented in
[ADR-004](adr/ADR-004-micro-batch-execution.md)) — a freshness decision, not a volume one.

## What to watch as you scale

The `pipeline_metrics` fact already trends the leading indicators: `join_match_rate` (skew /
stream alignment), `live_quarantined_rows` (upstream quality), row counts per stage (throughput),
and `risk_score_psi` (distribution stability). Watch these as volume grows — they will surface
a scaling problem before a user notices a slow or sparse dashboard.
