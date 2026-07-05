"""Delivery adapters + orchestration for fleet safety alerts (Slack + PagerDuty).

Separated from :mod:`fleet_alerting.alerts` (pure payload building) so network I/O is the only
thing not unit-tested against literal data. Both senders take an injectable ``transport``
(default: a stdlib ``urllib`` JSON POST) and a ``dry_run`` flag, so the whole path is
exercised offline — dev/CI with no webhook configured is a documented no-op, and tests assert
on the exact requests without a network or any accounts.

Delivery is **best-effort**: every failure is caught and logged, never raised. A safety-alert
channel being down must not fail the Gold run (whose data write already succeeded) — the
outcome is surfaced as a metric (``alerts_dispatch_errors``) on ``pipeline_metrics`` instead.
No third-party HTTP dependency is added; ``urllib`` from the stdlib is enough.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass

from fleet_alerting.alerts import notifiable, pagerduty_events, slack_payload

logger = logging.getLogger(__name__)

# PagerDuty Events API v2 enqueue endpoint (severity/dedup handled in the event payload).
PAGERDUTY_ENQUEUE_URL = "https://events.pagerduty.com/v2/enqueue"

_TIMEOUT_S = 10


@dataclass(frozen=True)
class AlertingConfig:
    """Where alerts go and at what severity. Empty secrets => that channel is disabled."""

    slack_webhook_url: str = ""
    pagerduty_routing_key: str = ""
    slack_min_severity: str = "warning"
    pagerduty_min_severity: str = "critical"
    dashboard_url: str = ""
    dry_run: bool = False

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_webhook_url)

    @property
    def pagerduty_enabled(self) -> bool:
        return bool(self.pagerduty_routing_key)

    @classmethod
    def from_getter(cls, get) -> AlertingConfig:
        """Build from a ``get(name, default)`` resolver (the notebook's ``get_param_or``).

        Reads ``SLACK_WEBHOOK_URL``, ``PAGERDUTY_ROUTING_KEY``, the two
        ``ALERTING_MIN_SEVERITY_*`` overrides, ``ALERTING_DASHBOARD_URL`` and
        ``ALERTING_DRY_RUN``. Any unset secret simply disables its channel.
        """
        truthy = ("1", "true", "yes", "on")
        return cls(
            slack_webhook_url=(get("SLACK_WEBHOOK_URL", "") or "").strip(),
            pagerduty_routing_key=(get("PAGERDUTY_ROUTING_KEY", "") or "").strip(),
            slack_min_severity=(get("ALERTING_MIN_SEVERITY_SLACK", "warning") or "warning").strip(),
            pagerduty_min_severity=(get("ALERTING_MIN_SEVERITY_PAGERDUTY", "critical") or "critical").strip(),
            dashboard_url=(get("ALERTING_DASHBOARD_URL", "") or "").strip(),
            dry_run=str(get("ALERTING_DRY_RUN", "") or "").strip().lower() in truthy,
        )


@dataclass(frozen=True)
class DispatchReport:
    """The outcome of one :func:`dispatch_alerts` call (recorded on ``pipeline_metrics``)."""

    considered: int  # notifiable alerts (max across channels)
    slack_sent: int
    pagerduty_sent: int
    errors: int
    dry_run: bool


def _http_post_json(url: str, body: dict) -> int:
    """POST ``body`` as JSON; return the HTTP status code.

    ``default=str`` so Spark-native values that reach a payload serialise instead of raising:
    PagerDuty's ``custom_details`` carries the alert's ``risk_score`` (a ``Decimal``) and
    ``timestamp`` (a ``datetime``) from ``collect()``, which vanilla ``json.dumps`` rejects — that
    silently failed every PagerDuty send (Slack only ever sends pre-formatted strings, so it was
    unaffected). Coercing to ``str`` is safe: PagerDuty renders ``custom_details`` values as text.
    """
    data = json.dumps(body, default=str).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310 — fixed https endpoints
        return int(getattr(resp, "status", 0) or resp.getcode())


def send_slack(webhook_url: str, payload: dict, *, dry_run: bool = False, transport=None) -> bool:
    """POST a Slack payload. Returns True if delivered (or would be, in dry-run). Never raises.

    Args:
        webhook_url: Slack Incoming Webhook URL.
        payload: The Slack JSON body (see :func:`fleet_alerting.alerts.slack_payload`).
        dry_run: If True, log and report success without sending.
        transport: Optional ``(url, body) -> status`` sender (defaults to a urllib POST).
    """
    if dry_run:
        logger.info("[dry-run] Slack alert: %s", str(payload.get("text", ""))[:200])
        return True
    if not webhook_url:
        return False
    try:
        status = (transport or _http_post_json)(webhook_url, payload)
        ok = 200 <= int(status) < 300
        if not ok:
            logger.warning("Slack webhook returned HTTP %s", status)
        return ok
    except Exception as exc:  # noqa: BLE001 — alerting is best-effort, never fatal
        logger.warning("Slack alert delivery failed: %s", exc)
        return False


def send_pagerduty(routing_key: str, event: dict, *, dry_run: bool = False, transport=None) -> bool:
    """POST one PagerDuty Events API v2 event. Returns True if accepted. Never raises.

    Args:
        routing_key: The PagerDuty integration routing key (empty => skip).
        event: The event dict (see :func:`fleet_alerting.alerts.pagerduty_event`).
        dry_run: If True, log and report success without sending.
        transport: Optional ``(url, body) -> status`` sender (defaults to a urllib POST).
    """
    if dry_run:
        logger.info("[dry-run] PagerDuty alert: %s", event.get("payload", {}).get("summary", ""))
        return True
    if not routing_key:
        return False
    try:
        status = (transport or _http_post_json)(PAGERDUTY_ENQUEUE_URL, event)
        ok = 200 <= int(status) < 300
        if not ok:
            logger.warning("PagerDuty returned HTTP %s", status)
        return ok
    except Exception as exc:  # noqa: BLE001 — alerting is best-effort, never fatal
        logger.warning("PagerDuty alert delivery failed: %s", exc)
        return False


def dispatch_alerts(
    rows,
    config: AlertingConfig,
    *,
    run_id: str | None = None,
    slack_transport=None,
    pagerduty_transport=None,
) -> DispatchReport:
    """Route alert ``rows`` to every configured channel; never raises.

    Slack gets a single batched message (from ``slack_min_severity`` up); PagerDuty gets one
    event per alert (from ``pagerduty_min_severity`` up), deduplicated per driver+severity. A
    channel with no secret is skipped unless ``dry_run`` is set (which exercises the whole path
    with no network).

    Args:
        rows: The alert rows (dicts with at least ``alert_type`` + the allowlisted fields).
        config: The resolved :class:`AlertingConfig`.
        run_id: Optional pipeline run id, embedded in the Slack message.
        slack_transport / pagerduty_transport: Optional injected senders (for tests).

    Returns:
        A :class:`DispatchReport` with per-channel counts and an error count.
    """
    slack_sent = pagerduty_sent = errors = considered = 0

    if config.slack_enabled or config.dry_run:
        s_alerts = notifiable(rows, config.slack_min_severity)
        considered = max(considered, len(s_alerts))
        if s_alerts:
            payload = slack_payload(s_alerts, run_id=run_id, dashboard_url=config.dashboard_url or None)
            if send_slack(config.slack_webhook_url, payload, dry_run=config.dry_run, transport=slack_transport):
                slack_sent = len(s_alerts)
            else:
                errors += 1

    if config.pagerduty_enabled or config.dry_run:
        p_alerts = notifiable(rows, config.pagerduty_min_severity)
        considered = max(considered, len(p_alerts))
        for event in pagerduty_events(p_alerts, config.pagerduty_routing_key or "DRYRUN"):
            if send_pagerduty(
                config.pagerduty_routing_key, event, dry_run=config.dry_run, transport=pagerduty_transport
            ):
                pagerduty_sent += 1
            else:
                errors += 1

    return DispatchReport(considered, slack_sent, pagerduty_sent, errors, config.dry_run)
