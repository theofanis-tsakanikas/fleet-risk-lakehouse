# ADR-009 — Pipeline-Triggered Alert Notifications (Slack + PagerDuty)

- **Status:** Accepted
- **Date:** 2026-07-04

## Context

The Gold layer already classifies every qualifying row into an `alert_type`
(`fleet_safety_alerts` — `CRITICAL` / `DANGER` / `WARNING` / `OVERSPEED`), and Grafana renders
them on a dashboard. But a dashboard is **pull**: it only helps someone who is already looking.
For a safety-critical signal — a driver operating dangerously *right now* — the alert must be
**pushed** to where an operator already is (a Slack channel) and, for the worst cases, to an
on-call escalation tool (PagerDuty). That is standard operations practice; without it the
"real-time risk monitoring" claim is half-built.

Two questions had to be answered:

1. **Where does the alert fire from — Grafana or the pipeline?** Grafana has native alerting
   with Slack/PagerDuty contact points, which is tempting (no code). But Grafana alerting would
   have to **poll the serverless SQL Warehouse** on a schedule; the warehouse auto-stops after
   10 minutes (ADR-003), so every evaluation either keeps it warm (cost) or eats a cold start,
   and the alert rules would **duplicate** the classification the pipeline already computes.
2. **How do we avoid leaking special-category data to a third-party SaaS?** The alert rows
   carry GDPR Art. 9 biometrics (`heart_rate` / `stress_score`). The UC column masks (ADR-007)
   protect *reads*, but the pipeline principal reads raw values — naively serialising an alert
   row to Slack would exfiltrate Art. 9 data straight past the masking boundary.

## Decision

**Fire alerts from the Databricks pipeline itself** (the Gold run), not from Grafana. A new
pure, unit-tested package `src/fleet_alerting/` — mirroring the project's discipline
(`fleet_transforms` / `fleet_governance`) — turns the already-classified alert rows into
notifications and dispatches them at the end of each Gold run:

- **`alerts.py` (pure):** severity mapping (`alert_type` leading keyword → `critical` /
  `warning` / `none`), severity-floor filtering, and the Slack / PagerDuty payload builders.
- **`dispatch.py` (I/O + orchestration):** an `AlertingConfig` (resolved from job
  params/secrets), stdlib-`urllib` delivery adapters with an injectable transport and a
  `dry_run` mode, and `dispatch_alerts()` which routes to each configured channel.

Key properties:

- **Severity routing.** Slack receives everything from `warning` up (team awareness);
  PagerDuty pages only on `critical` (`CRITICAL` / `DANGER`), deduplicated per driver+severity
  so a persistent offender does not spam the on-call responder. Both floors are configurable.
- **No special-category data leaves the platform.** The outgoing payload is built from an
  **allowlist** (`NOTIFY_FIELDS`: timestamp, driver/truck id, speed, risk score, primary
  factor, alert type). A test asserts the allowlist is disjoint from
  `classification.special_category_columns()`, and the notebook's source query selects only
  those columns — so biometrics are excluded **by construction**, not by remembering to.
- **Best-effort, never fatal.** Every delivery failure is caught and logged, never raised; the
  outcome is surfaced as `alerts_dispatch_errors` on `pipeline_metrics`. A Slack outage must
  not fail a Gold run whose data write already succeeded.
- **Zero new dependency / zero-config default.** Delivery uses stdlib `urllib`. With no webhook
  / routing key configured (the default), the step is a documented no-op that logs what it
  *would* have sent — so dev/CI and the committed bundle run unchanged, and enabling alerts is
  purely a matter of injecting the secrets (via a Databricks secret scope in production).

Grafana keeps its role as the human-facing dashboard (pull); this is strictly the push path.

## Consequences

- Alerts are **event-driven**, firing exactly when the run computes them — aligned with the
  micro-batch model (ADR-004), with no extra warehouse queries and no duplicated alert logic.
- The Art. 9 boundary is preserved end-to-end: masking protects reads (ADR-007), and the
  allowlist protects external notifications. The generated Art. 30 record (ADR docs) now names
  Slack/PagerDuty as recipients and states that special-category data is never sent externally.
- Adding a channel (e.g. Microsoft Teams, Opsgenie) is a new adapter + config field; the pure
  filtering/severity logic is reused unchanged.

### Trade-offs

- The notification content is intentionally minimal (no biometrics) — a responder who needs the
  full physiological context opens the (masked, access-controlled) Gold table, not the Slack
  message. That is the correct privacy posture, not a limitation.
- Delivery being best-effort means a silently failing webhook is possible; that risk is
  mitigated by the `alerts_dispatch_errors` metric (trend it in Grafana) rather than by failing
  the pipeline.
- The bundle ships empty secret defaults; real deployments must wire a secret scope. This is the
  same pattern the rest of the project uses (no secrets in version control).

### When to revisit

- If alert volume grows, add rate-limiting / grouping windows (e.g. one digest per driver per
  hour) in `dispatch.py`.
- If an acknowledgement/resolution loop is wanted, extend the PagerDuty adapter to emit
  `resolve` events keyed by the existing `dedup_key` once a driver returns to normal.
