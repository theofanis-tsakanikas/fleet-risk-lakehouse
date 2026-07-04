"""Fleet safety-alert notifications (Slack + PagerDuty), triggered from the pipeline.

The Gold layer already classifies every qualifying row into an ``alert_type``
(``fleet_safety_alerts``). This package pushes the serious ones (CRITICAL / DANGER, and
optionally WARNING / OVERSPEED) to external channels **from the Databricks pipeline itself**
— event-driven, at the end of each Gold run — rather than by polling the SQL Warehouse from
Grafana (see ``docs/adr/ADR-009-alert-notifications.md``). Grafana stays the human-facing
dashboard; this is the push path.

* :mod:`fleet_alerting.alerts` — pure payload building (rows in, dicts out; zero network).
* :mod:`fleet_alerting.dispatch` — config + delivery adapters (Slack / PagerDuty), with a
  ``dry_run`` mode so it runs offline and unit-tests without a network or any accounts.
"""
