"""Tests for the fleet alerting layer (Slack + PagerDuty), all network-free.

Pure payload logic is asserted against literal rows; the delivery adapters are driven with an
injected transport and the ``dry_run`` flag, so nothing here touches a network or needs an
account. The governance guarantee — no special-category biometric ever leaves the platform —
is locked against the live classification, not a hand-kept list.
"""

from __future__ import annotations

from fleet_alerting.alerts import (
    NOTIFY_FIELDS,
    notifiable,
    pagerduty_event,
    pagerduty_events,
    safe_view,
    severity_of,
    slack_payload,
)
from fleet_alerting.dispatch import (
    AlertingConfig,
    DispatchReport,
    dispatch_alerts,
    send_pagerduty,
    send_slack,
)
from fleet_governance.classification import special_category_columns

# A representative batch of alert rows, deliberately carrying raw biometrics so the tests can
# prove they never reach an outgoing payload.
_ROWS = [
    {
        "timestamp": "2026-07-04T10:00:00",
        "driver_id": "DRV_01",
        "truck_id": "TRK-701",
        "speed": 128,
        "heart_rate": 165,  # Art. 9 — must never be sent
        "stress_score": 88,  # Art. 9 — must never be sent
        "risk_score": 91.0,
        "risk_primary_factor": "speed",
        "alert_type": "CRITICAL: High Speed & Stress",
    },
    {
        "timestamp": "2026-07-04T10:01:00",
        "driver_id": "DRV_02",
        "truck_id": "TRK-702",
        "speed": 70,
        "heart_rate": 118,
        "stress_score": 40,
        "risk_score": 62.0,
        "risk_primary_factor": "heart_rate",
        "alert_type": "DANGER: Extreme Heart Rate",
    },
    {
        "timestamp": "2026-07-04T10:02:00",
        "driver_id": "DRV_03",
        "truck_id": "TRK-703",
        "speed": 95,
        "heart_rate": 84,
        "stress_score": 30,
        "risk_score": 48.0,
        "risk_primary_factor": "speed",
        "alert_type": "OVERSPEED",
    },
    {
        "timestamp": "2026-07-04T10:03:00",
        "driver_id": "DRV_04",
        "truck_id": "TRK-704",
        "speed": 60,
        "heart_rate": 70,
        "stress_score": 10,
        "risk_score": 20.0,
        "risk_primary_factor": "none",
        "alert_type": "NORMAL",
    },
]


class _Recorder:
    """A fake transport that records calls and returns a fixed status."""

    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, body: dict) -> int:
        self.calls.append((url, body))
        return self.status


# --- severity + filtering ------------------------------------------------------------------ #


def test_severity_of_maps_by_leading_keyword():
    assert severity_of("CRITICAL: High Speed & Stress") == "critical"
    assert severity_of("DANGER: Extreme Heart Rate") == "critical"
    assert severity_of("WARNING: Elevated Heart Rate") == "warning"
    assert severity_of("OVERSPEED") == "warning"
    assert severity_of("NORMAL") == "none"
    assert severity_of("") == "none"


def test_notifiable_warning_floor_keeps_all_real_alerts_drops_normal():
    out = notifiable(_ROWS, "warning")
    types = [a["alert_type"] for a in out]
    assert "NORMAL" not in types
    assert len(out) == 3  # critical + danger + overspeed


def test_notifiable_critical_floor_excludes_warnings():
    out = notifiable(_ROWS, "critical")
    assert {a["severity"] for a in out} == {"critical"}
    assert len(out) == 2  # CRITICAL + DANGER only


def test_notifiable_orders_most_severe_first():
    out = notifiable(_ROWS, "warning")
    assert out[0]["severity"] == "critical"
    assert out[-1]["severity"] == "warning"


# --- the governance guarantee -------------------------------------------------------------- #


def test_notify_fields_exclude_special_category():
    # The allowlist must share no column with the governed special-category set.
    assert set(NOTIFY_FIELDS).isdisjoint(set(special_category_columns()))


def test_safe_view_drops_biometrics():
    view = safe_view(_ROWS[0])
    assert "heart_rate" not in view
    assert "stress_score" not in view
    assert view["driver_id"] == "DRV_01"
    assert view["risk_score"] == 91.0


def test_slack_payload_never_contains_biometric_values():
    payload = slack_payload(notifiable(_ROWS, "warning"), run_id="run-1")
    blob = str(payload)
    # The raw biometric *values* must never appear (the factor *name* "heart_rate" may — it is
    # the risk_primary_factor label, not a health reading).
    for raw in ("165", "118", "84", "88"):  # heart rates + a stress score
        assert raw not in blob
    assert "DRV_01" in blob and "CRITICAL" in blob


def test_pagerduty_event_custom_details_have_no_biometrics():
    ev = pagerduty_event(notifiable(_ROWS, "critical")[0], "RK")
    assert "heart_rate" not in ev["payload"]["custom_details"]
    assert "stress_score" not in ev["payload"]["custom_details"]


# --- payload shapes ------------------------------------------------------------------------ #


def test_slack_payload_has_text_and_counts():
    payload = slack_payload(notifiable(_ROWS, "warning"))
    assert set(payload) == {"text"}
    assert "3 alert(s)" in payload["text"]
    assert "2 critical" in payload["text"]


def test_slack_payload_caps_body_and_summarises_overflow():
    many = [dict(_ROWS[0], driver_id=f"DRV_{i:02d}") for i in range(25)]
    payload = slack_payload(notifiable(many, "warning"))
    assert "and 5 more" in payload["text"]


def test_pagerduty_event_schema_and_dedup():
    by_driver = {a["driver_id"]: a for a in notifiable(_ROWS, "critical")}
    ev = pagerduty_event(by_driver["DRV_01"], "ROUTE_KEY")
    assert ev["routing_key"] == "ROUTE_KEY"
    assert ev["event_action"] == "trigger"
    assert ev["payload"]["severity"] == "critical"
    assert ev["dedup_key"] == "fleet:DRV_01:critical"


def test_pagerduty_events_one_per_alert():
    events = pagerduty_events(notifiable(_ROWS, "warning"), "RK")
    assert len(events) == 3


# --- config -------------------------------------------------------------------------------- #


def test_config_from_getter_parses_and_flags():
    env = {
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/x",
        "PAGERDUTY_ROUTING_KEY": "",
        "ALERTING_DRY_RUN": "true",
    }
    cfg = AlertingConfig.from_getter(lambda k, d="": env.get(k, d))
    assert cfg.slack_enabled is True
    assert cfg.pagerduty_enabled is False
    assert cfg.dry_run is True
    assert cfg.slack_min_severity == "warning"
    assert cfg.pagerduty_min_severity == "critical"


# --- delivery adapters --------------------------------------------------------------------- #


def test_send_slack_dry_run_does_not_call_transport():
    rec = _Recorder()
    assert send_slack("https://x", {"text": "hi"}, dry_run=True, transport=rec) is True
    assert rec.calls == []


def test_send_slack_no_webhook_is_skip():
    assert send_slack("", {"text": "hi"}) is False


def test_send_slack_uses_transport_and_reads_status():
    ok = _Recorder(200)
    assert send_slack("https://x", {"text": "hi"}, transport=ok) is True
    assert ok.calls[0][0] == "https://x"

    bad = _Recorder(500)
    assert send_slack("https://x", {"text": "hi"}, transport=bad) is False


def test_send_slack_never_raises_on_transport_error():
    def boom(url, body):
        raise RuntimeError("network down")

    assert send_slack("https://x", {"text": "hi"}, transport=boom) is False


def test_send_pagerduty_posts_to_events_endpoint():
    rec = _Recorder(202)
    ev = pagerduty_event(notifiable(_ROWS, "critical")[0], "RK")
    assert send_pagerduty("RK", ev, transport=rec) is True
    assert rec.calls[0][0].endswith("/v2/enqueue")


def test_send_pagerduty_never_raises():
    def boom(url, body):
        raise RuntimeError("nope")

    ev = pagerduty_event(notifiable(_ROWS, "critical")[0], "RK")
    assert send_pagerduty("RK", ev, transport=boom) is False


# --- orchestration ------------------------------------------------------------------------- #


def test_dispatch_dry_run_counts_without_network():
    cfg = AlertingConfig(dry_run=True)
    report = dispatch_alerts(_ROWS, cfg, run_id="r1")
    assert isinstance(report, DispatchReport)
    assert report.dry_run is True
    assert report.slack_sent == 3  # warning floor
    assert report.pagerduty_sent == 2  # critical floor
    assert report.errors == 0


def test_dispatch_slack_only_routes_correctly():
    slack = _Recorder(200)
    pager = _Recorder(200)
    cfg = AlertingConfig(slack_webhook_url="https://hooks.slack.com/x")
    report = dispatch_alerts(_ROWS, cfg, slack_transport=slack, pagerduty_transport=pager)
    assert report.slack_sent == 3
    assert report.pagerduty_sent == 0  # pagerduty disabled (no routing key)
    assert len(slack.calls) == 1
    assert pager.calls == []


def test_dispatch_counts_errors_and_never_raises():
    cfg = AlertingConfig(slack_webhook_url="https://x", pagerduty_routing_key="RK")
    report = dispatch_alerts(
        _ROWS,
        cfg,
        slack_transport=_Recorder(500),  # slack fails
        pagerduty_transport=_Recorder(202),  # pagerduty ok
    )
    assert report.slack_sent == 0
    assert report.errors >= 1
    assert report.pagerduty_sent == 2


def test_dispatch_no_config_no_channels():
    report = dispatch_alerts(_ROWS, AlertingConfig())
    assert report.slack_sent == 0
    assert report.pagerduty_sent == 0
    assert report.errors == 0
