# Operations Runbook

Operational reference for running, observing, and recovering the Fleet Risk Lakehouse
pipeline. For environment setup and the engineering reference see [CLAUDE.md](../CLAUDE.md);
for design rationale see the [ADRs](adr/).

---

## Service overview

| Property | Value |
|---|---|
| Pipeline jobs | `fleet_monitoring_job` (DABs, 8 tasks — mock data, manual) · `fleet_replay_job` (8 tasks — **real VED data**, see [ADR-008](adr/ADR-008-real-data-replay.md)) |
| Trigger | Monitoring: manual. Replay: 30-min periodic trigger, **PAUSED by default** (`var.replay_pause_status`) — unpause for continuous operation (micro-batch per run — see [ADR-004](adr/ADR-004-micro-batch-execution.md)) |
| Max concurrent runs | 1 per job (checkpoint safety) |
| Job timeout | 7200s (2h) |
| BI serving | Grafana + Streamlit over the serverless SQL Warehouse |
| Warehouse auto-stop | 10 min idle |

### The DAG (identical medallion chain in both jobs)

```
generate_mock_trackers ─► bronze_trackers ─► silver_trackers ─┬─► gold_fleet_enrichment
                                                              ├─► build_dim_driver
generate_mock_watches  ─► bronze_watches  ─► silver_watches  ─┘
```

`build_dim_driver` depends only on `silver_trackers` and runs in parallel with Gold. In
`fleet_replay_job` the two generator tasks are `replay_trackers` / `replay_watches`
(real VED trips, pseudonymised, anchored to `{{job.start_time}}`); everything downstream
is byte-identical (YAML aliases of the same task definitions).

---

## Expected latency & cost (order-of-magnitude)

These are rough, dev-scale (10 drivers) figures to set expectations — measure your own.

| Stage | Wall-clock (dev) | Cost driver |
|---|---|---|
| `terraform 01_infra apply` | 8–12 min | one-time / infra changes |
| `terraform 02/03 apply` | 3–5 min each | one-time / infra changes |
| Full pipeline run | a few min | job compute (environment v2) |
| First Grafana query after idle | 20–30 s | SQL Warehouse cold start |
| Warehouse warm query | sub-second | serverless, scales to 2 clusters |

Cost levers: the warehouse **auto-stops after 10 min** (idle cost ≈ 0); the job releases
compute when it finishes (no always-on cluster — that is the point of micro-batch). The S3
landing zone has a 7-day lifecycle rule on `temp/`.

---

## Observability — where to look first

- **`pipeline_metrics`** (Gold metadata schema): tall fact, one row per `(run_id, stage,
  metric, value)`. Trend it in Grafana. Key metrics per run:
  - `enriched_rows`, `live_status_rows`, `safety_metrics_rows`, `safety_alerts_rows`
  - `live_quarantined_rows` — rows that failed an ERROR expectation
  - `join_match_rate` — fraction of watch-drivers that matched a tracker in the ±60s window
  - `risk_score_psi` + `dist_band_*` — risk-score distribution & drift
- **`fleet_live_status_quarantine`**: the actual bad rows, annotated with `_dq_failures`.
- **Job task logs**: every DQ expectation logs `name: failed/total violated`; the empty-view
  and metrics guards log their pass/fail explicitly.

---

## Alerts & thresholds

| Signal | Where | Meaning / action |
|---|---|---|
| `join_match_rate` ≪ historical | `pipeline_metrics` | Streams drifting apart in time → see "Gold empty / sparse" below |
| `risk_score_psi` ≥ 0.1 (moderate), ≥ 0.25 (significant) | `pipeline_metrics`, task log WARN | Distribution shifted. **Suspect a sensor recalibration / units bug upstream before concluding the fleet got more dangerous.** Drift is logged, not fatal. |
| `live_quarantined_rows` > 0 | `pipeline_metrics`, quarantine table | Inspect `_dq_failures`; common cause is upstream sensor garbage that escaped Silver. |
| Run failed with `DataQualityError` | task log | An ERROR expectation breached — message lists which and how many. |

---

## Common incidents

### 1. Gold tables empty or run fails with "fleet_enriched_view has 0 rows"

**Cause:** the ±60s temporal join found no overlapping events — almost always the two Silver
streams have non-overlapping timestamp ranges (one ran long before the other), not a code bug.
See [ADR-002](adr/ADR-002-temporal-join-window.md) and Known Gotcha #1 in CLAUDE.md.

**Action:**
1. Check `silver_trackers` / `silver_watches` for overlapping `event_timestamp` ranges.
2. Confirm both `generate_mock_*` tasks ran in the same window (they sync to start-of-minute).
3. Re-run the job so both streams land contemporaneous batches.

### 2. Run fails with `DataQualityError`

**Cause:** an ERROR expectation on `fleet_live_status` was violated (null key, `risk_score`
out of `[0, cap]`). The valid rows were still written and the bad rows are in the quarantine
table.

**Action:** read the error (it names the expectation + count) → inspect
`fleet_live_status_quarantine` `_dq_failures` → fix the upstream cause (usually a Silver rule
gap). The suite is in `fleet_transforms.gold.live_status_expectations`.

### 3. Biometrics show as NULL / location looks coarse in a dashboard

**Not a bug.** Column masks ([ADR-007](adr/ADR-007-column-masking.md)) redact biometrics and
coarsen location for principals outside the `fleet_safety_officers` group. Confirm the
querying principal's group membership; grant it if the access is legitimate.

### 4. `risk_score_psi` flagged significant

Drift is a **signal, not a failure**. Before treating it as a real safety change, rule out: a
recalibrated/replaced sensor cohort, a units change upstream, or a generator config change.
Compare `dist_band_*` across recent runs in `pipeline_metrics`.

### 5. Layer 02/03 plan/apply fails with an auth error on a fresh clone

Layer `01_infra` must be applied first so the SPN credentials exist in Secrets Manager;
`terraform.sh` injects them for layers 02/03. See Known Gotcha #2 in CLAUDE.md.

---

## Recovery & re-runs

- Runs are **idempotent**: Gold uses `CREATE OR REPLACE TABLE`, the SCD2 MERGE produces no new
  versions for an unchanged snapshot, and Bronze/Silver checkpoints prevent reprocessing.
- Re-running after a transient failure is safe. There is no partial streaming state to clean
  up (micro-batch — [ADR-004](adr/ADR-004-micro-batch-execution.md)).
- `pipeline_metrics` and the quarantine table are **append-only** — a re-run adds a new
  `run_id`; it does not overwrite history.
