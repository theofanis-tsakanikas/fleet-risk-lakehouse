"""Pure alert-notification logic: severity, filtering, and payload building.

The Gold layer already classifies every qualifying row into an ``alert_type``
(``fleet_safety_alerts`` — ``CRITICAL`` / ``DANGER`` / ``WARNING`` / ``OVERSPEED``). This
module turns those rows into notifications for external channels **without re-deriving the
alerting rules**: it reads the classification the pipeline already made.

Two deliberate design choices, both enforced by tests here:

* **Severity-based routing.** Each ``alert_type`` maps to a severity (``critical`` /
  ``warning`` / ``none``) by its leading keyword, so a channel can declare a minimum severity
  — PagerDuty pages only on ``critical`` while Slack sees everything from ``warning`` up.
* **No special-category data leaves the platform.** GDPR Art. 9 biometrics (``heart_rate`` /
  ``stress_score``) are **never** put in an external message: the notification is projected
  onto :data:`NOTIFY_FIELDS`, an allowlist of operational/derived fields, and a test asserts
  that allowlist shares no column with ``classification.special_category_columns()``. Masking
  at the UC read boundary (ADR-007) would not help here — serialising a row straight to Slack
  would still exfiltrate it — so building the payload from an allowlist closes the hole by
  construction. See ``docs/adr/ADR-009-alert-notifications.md``.

Everything here is pure (rows in, dicts out), so it unit-tests with zero network.
"""

from __future__ import annotations

# alert_type leading keyword -> severity. Robust to the exact wording after the colon
# (e.g. "CRITICAL: High Speed & Stress" -> "critical").
_CRITICAL = frozenset({"CRITICAL", "DANGER"})
_WARNING = frozenset({"WARNING", "OVERSPEED"})

# Severity ordering, for "minimum severity" comparisons.
_RANK = {"none": 0, "warning": 1, "critical": 2}

# The ONLY fields allowed into an external notification: operational + derived + identifiers.
# Deliberately excludes special-category biometrics (heart_rate / stress_score) — enforced by
# ``test_notify_fields_exclude_special_category`` against the governance classification.
NOTIFY_FIELDS: tuple[str, ...] = (
    "timestamp",
    "driver_id",
    "truck_id",
    "speed",
    "risk_score",
    "risk_primary_factor",
    "alert_type",
)


def severity_of(alert_type: str) -> str:
    """Map an ``alert_type`` to ``critical`` / ``warning`` / ``none`` by its leading keyword."""
    key = (alert_type or "").split(":")[0].strip().upper()
    if key in _CRITICAL:
        return "critical"
    if key in _WARNING:
        return "warning"
    return "none"


def _rank(severity: str) -> int:
    return _RANK.get(severity, 0)


def safe_view(row: dict) -> dict:
    """Project ``row`` onto :data:`NOTIFY_FIELDS` (drops biometrics and anything unlisted)."""
    return {k: row.get(k) for k in NOTIFY_FIELDS}


def notifiable(rows, min_severity: str = "warning") -> list[dict]:
    """The alerts worth sending at or above ``min_severity``, most-severe first.

    Each returned dict is a :func:`safe_view` of its row plus a ``severity`` key. Rows whose
    ``alert_type`` is not an alert (severity ``none``) are dropped regardless of the floor.

    Args:
        rows: Iterable of alert rows (dicts) with at least an ``alert_type`` key.
        min_severity: The lowest severity to include (``warning`` or ``critical``).

    Returns:
        The allowlisted, severity-annotated alerts, sorted by severity then timestamp desc.
    """
    floor = _rank(min_severity)
    out = []
    for row in rows:
        sev = severity_of(row.get("alert_type", ""))
        if sev != "none" and _rank(sev) >= floor:
            view = safe_view(row)
            view["severity"] = sev
            out.append(view)
    # Most-severe first, then newest first within a severity (stable two-pass sort).
    out.sort(key=lambda a: str(a.get("timestamp")), reverse=True)
    out.sort(key=lambda a: _rank(a["severity"]), reverse=True)
    return out


def _fmt_alert_line(a: dict) -> str:
    return (
        f"• *{a.get('alert_type')}* — driver `{a.get('driver_id')}` "
        f"(truck `{a.get('truck_id')}`) · risk *{a.get('risk_score')}* "
        f"· speed {a.get('speed')} · primary: {a.get('risk_primary_factor')}"
    )


# Slack caps a readable message body; extras are summarised as "and N more".
_SLACK_BODY_CAP = 20


def slack_payload(alerts: list[dict], *, run_id: str | None = None, dashboard_url: str | None = None) -> dict:
    """Build a Slack Incoming-Webhook JSON payload for a batch of alerts.

    Uses only allowlisted fields (see :func:`safe_view`) — no biometrics ever.

    Args:
        alerts: Severity-annotated safe views (see :func:`notifiable`).
        run_id: Optional pipeline run id, appended for traceability.
        dashboard_url: Optional Grafana/Streamlit link for the responder.

    Returns:
        A ``{"text": ...}`` dict ready to POST to a Slack Incoming Webhook.
    """
    n = len(alerts)
    crit = sum(1 for a in alerts if a.get("severity") == "critical")
    header = f"🚨 Fleet safety: {n} alert(s) — {crit} critical"
    lines = "\n".join(_fmt_alert_line(a) for a in alerts[:_SLACK_BODY_CAP])
    text = f"*{header}*\n{lines}" if lines else f"*{header}*"
    if n > _SLACK_BODY_CAP:
        text += f"\n… and {n - _SLACK_BODY_CAP} more."
    if run_id:
        text += f"\n_run {run_id}_"
    if dashboard_url:
        text += f"\n<{dashboard_url}|Open the fleet dashboard>"
    return {"text": text}


def pagerduty_event(alert: dict, routing_key: str, *, source: str = "fleet-risk-lakehouse") -> dict:
    """One PagerDuty Events API v2 ``trigger`` event for a single alert (allowlisted fields).

    ``dedup_key`` collapses repeated pages for the same driver+severity into one incident, so a
    driver who keeps breaching does not spam the on-call responder.

    Args:
        alert: A severity-annotated safe view (see :func:`notifiable`).
        routing_key: The PagerDuty integration (Events API v2) routing key.
        source: The ``source`` field of the event payload.

    Returns:
        A dict matching the PagerDuty Events API v2 enqueue schema.
    """
    driver = alert.get("driver_id")
    atype = alert.get("alert_type")
    return {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": f"fleet:{driver}:{alert.get('severity', severity_of(atype))}",
        "payload": {
            "summary": f"{atype} — driver {driver} (risk {alert.get('risk_score')})",
            "severity": "critical" if alert.get("severity") == "critical" else "warning",
            "source": source,
            "component": "fleet-gold",
            "custom_details": safe_view(alert),
        },
    }


def pagerduty_events(alerts: list[dict], routing_key: str, *, source: str = "fleet-risk-lakehouse") -> list[dict]:
    """One :func:`pagerduty_event` per alert."""
    return [pagerduty_event(a, routing_key, source=source) for a in alerts]
