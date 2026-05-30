# ADR-002: 60-Second Symmetric Temporal Join Window for Tracker–Watch Correlation

**Date:** 2024-06  
**Status:** Accepted

---

## Context

The Gold layer must correlate two independent IoT streams for the same driver at approximately the same point in time:

- **Vehicle trackers** — GPS coordinates, speed, fuel level. Produced as CSV batches; default mock interval is 120 seconds per batch covering 5 records.
- **Smartwatches** — heart rate, stress score, steps. Produced as JSON batches on the same interval.

These streams have no shared event bus, no synchronized clock, and no guaranteed alignment. A GPS unit and a smartwatch on the same driver will emit events independently at times that differ by seconds to minutes depending on firmware, network latency, and batch scheduling.

A direct equijoin on `(driver_id, event_timestamp)` — requiring the exact same millisecond timestamp — would produce zero rows in practice. The join window must be wide enough to correlate contemporary events while narrow enough to avoid joining readings from different driving contexts (e.g., a parked idle reading joined with a high-speed segment from two minutes earlier).

---

## Decision

Use a symmetric window join in SQL:

```sql
t.event_timestamp BETWEEN w.event_timestamp - INTERVAL 60 SECONDS
                       AND w.event_timestamp + INTERVAL 60 SECONDS
```

The window is expressed relative to the watch event timestamp (`w.event_timestamp`). For each watch event, the join matches any tracker event for the same driver within ±60 seconds.

**Why 60 seconds specifically:**

The mock generators produce batches with a 120-second interval. The ±60s window ensures that the watch event at time `T` will match the tracker event produced in the same batch (which may be anywhere from 0 to ~120 seconds away, depending on intra-batch timing). A window smaller than ~60s risks missing valid same-segment pairs. A window larger than 120s risks matching the watch event at time `T` with a tracker event from the *next* or *previous* batch interval — a different driving moment.

In production, real GPS units typically sample every 30–60 seconds and smartwatch sync intervals are 30–120 seconds. The 60s window covers the majority of real-world same-segment pairs.

---

## Consequences

**Benefits**

- Reliably correlates the two streams without requiring synchronized clocks or a shared event bus.
- The window is a single SQL constant — easy to understand, tune, and explain to stakeholders.
- Aligns with the mock generator's 120-second batch interval, ensuring the integration test baseline always produces correlated Gold rows.

**Trade-offs**

- **INNER JOIN semantics**: drivers with tracker events but no watch events within ±60 seconds are excluded from all three Gold tables. This is intentional — a risk score without biometric data is not meaningful — but it means the Gold table row count is always ≤ the Silver tracker row count.
- **Multiple matches per watch event**: if a driver produces two tracker GPS pings within the ±60s window, both match and produce two Gold rows for that watch event. `fleet_live_status` resolves this with `ROW_NUMBER() OVER (PARTITION BY driver_id ORDER BY timestamp DESC)` to keep only the most recent record per driver. `fleet_safety_alerts` intentionally retains all matched rows.
- **Silent failure mode**: if the two Silver streams have completely non-overlapping timestamp ranges (e.g., trackers ran yesterday and watches ran today), the INNER JOIN returns zero rows and all three Gold tables are overwritten as empty with no error from Spark itself. The Gold notebook's row-count assertion on `fleet_enriched_view` catches this case and raises a `ValueError` to fail the job task with a meaningful message.
- The 60-second threshold was calibrated against the mock generator. In production, this value should be revisited against actual device telemetry frequency.
