"""Data layer for the Fleet Safety Command Center UI.

This module produces the three Gold business tables the dashboard renders:

    * ``fleet_live_status``    — latest enriched record per driver
    * ``driver_safety_metrics`` — hourly per-driver aggregates
    * ``fleet_safety_alerts``   — historical alert log

Two sources are supported behind one interface (``load_gold``):

    * **Demo mode** (default) — synthesises a realistic, self-contained dataset
      from the project's *real* ``fleet_config.json`` and the *exact* Gold
      ``risk_score`` / alert-classification logic from
      ``src/fleet_transforms/gold.py``. It needs no Databricks cluster, no
      cloud credentials and costs nothing — ideal for a demo / promo recording.
    * **Databricks SQL** — reads the live Gold Delta tables over a serverless
      SQL Warehouse via ``databricks-sql-connector``.

Keeping the risk formula and alert thresholds here byte-for-byte identical to
the Spark SQL in ``gold.py`` means the dashboard shows the same numbers the real
pipeline would write — the demo is faithful, not invented.
"""

from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------- #
# Fleet roster — loaded from the project's real config (single source of truth)
# --------------------------------------------------------------------------- #

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "mock_generator"
    / "fleet_config.json"
)

# Embedded fallback so the app still runs if it is copied out of the repo.
_FALLBACK_ROSTER = [
    {"driver_id": "DRV_01", "truck_id": "TRK-701", "name": "John Doe"},
    {"driver_id": "DRV_02", "truck_id": "TRK-702", "name": "Alice Smith"},
    {"driver_id": "DRV_03", "truck_id": "TRK-703", "name": "Robert Brown"},
    {"driver_id": "DRV_04", "truck_id": "TRK-704", "name": "Emily Davis"},
    {"driver_id": "DRV_05", "truck_id": "TRK-705", "name": "Michael Wilson"},
    {"driver_id": "DRV_06", "truck_id": "TRK-706", "name": "Sarah Miller"},
    {"driver_id": "DRV_07", "truck_id": "TRK-707", "name": "David Taylor"},
    {"driver_id": "DRV_08", "truck_id": "TRK-708", "name": "James Anderson"},
    {"driver_id": "DRV_09", "truck_id": "TRK-709", "name": "Linda Thomas"},
    {"driver_id": "DRV_10", "truck_id": "TRK-710", "name": "William Moore"},
]


def load_roster() -> list[dict]:
    """Return the driver/truck roster from ``fleet_config.json`` (or fallback)."""
    try:
        with open(_CONFIG_PATH, "r") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return _FALLBACK_ROSTER


# Athens operating area — same centre the mock GPS generator uses.
_ATHENS_LAT, _ATHENS_LON = 37.9838, 23.7275


# --------------------------------------------------------------------------- #
# Gold business logic — mirrors src/fleet_transforms/gold.py exactly
# --------------------------------------------------------------------------- #

def compute_risk_score(speed: float, stress: float, heart_rate: float) -> float:
    """Weighted driver risk score, identical to the Gold SQL formula.

    ``LEAST(100, speed/120*40 + stress/100*35 + heart_rate/110*25)`` with NULLs
    coalesced to 0 and the result rounded to 2 decimals. See
    ``enriched_view_select_sql`` in ``src/fleet_transforms/gold.py``.
    """
    speed = speed or 0
    stress = stress or 0
    heart_rate = heart_rate or 0
    raw = (
        (speed / 120.0 * 40)
        + (stress / 100.0 * 35)
        + (heart_rate / 110.0 * 25)
    )
    return round(min(100.0, raw), 2)


def classify_alert(speed: float, heart_rate: float) -> str:
    """Alert classification identical to ``safety_alerts_select_sql``."""
    if speed > 90 and heart_rate > 90:
        return "CRITICAL: High Speed & Stress"
    if heart_rate > 110:
        return "DANGER: Extreme Heart Rate"
    if heart_rate > 90:
        return "WARNING: Elevated Heart Rate"
    if speed > 90:
        return "OVERSPEED"
    return "NORMAL"


# --------------------------------------------------------------------------- #
# Demo data synthesis
# --------------------------------------------------------------------------- #

# Per-driver behavioural profiles so the leaderboard tells a story: a couple of
# consistently risky drivers, a safe majority, a few in between. Values are
# (speed_mean, speed_sd, hr_mean, hr_sd, stress_mean, stress_sd).
_PROFILES = {
    "reckless": (92, 9, 96, 10, 72, 16),
    "elevated": (84, 8, 88, 9, 58, 15),
    "steady": (74, 7, 78, 7, 40, 13),
    "calm": (66, 6, 72, 6, 28, 10),
}

# Deterministic assignment keyed by driver_id so the same driver keeps the same
# character across reruns (only the per-tick noise changes when re-seeded).
_PROFILE_ORDER = ["reckless", "elevated", "steady", "steady", "calm",
                  "elevated", "calm", "steady", "reckless", "calm"]


@dataclass
class GoldTables:
    """The three Gold tables plus the per-event enriched frame for drill-downs."""

    live_status: pd.DataFrame
    safety_metrics: pd.DataFrame
    safety_alerts: pd.DataFrame
    enriched: pd.DataFrame


def _gauss_clamped(rng: random.Random, mean: float, sd: float,
                   lo: float, hi: float) -> float:
    return max(lo, min(hi, rng.gauss(mean, sd)))


def generate_demo_enriched(hours: int = 6, step_minutes: int = 3,
                           seed: int | None = 42) -> pd.DataFrame:
    """Synthesise the enriched per-event frame (the Gold join input).

    Produces one correlated tracker+watch record per driver every
    ``step_minutes`` over the last ``hours``, applies the real ``risk_score``
    formula, and walks each truck on a small random route around Athens so the
    map shows distinct, moving vehicles.
    """
    rng = random.Random(seed)
    roster = load_roster()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    n_steps = max(1, (hours * 60) // step_minutes)

    rows: list[dict] = []
    for idx, drv in enumerate(roster):
        profile = _PROFILE_ORDER[idx % len(_PROFILE_ORDER)]
        s_mean, s_sd, hr_mean, hr_sd, st_mean, st_sd = _PROFILES[profile]

        # Each truck starts at a distinct spot in the Athens area and drifts.
        angle = (idx / max(1, len(roster))) * 2 * math.pi
        lat = _ATHENS_LAT + 0.06 * math.sin(angle)
        lon = _ATHENS_LON + 0.06 * math.cos(angle)

        for k in range(n_steps):
            ts = now - timedelta(minutes=step_minutes * (n_steps - 1 - k))
            speed = round(_gauss_clamped(rng, s_mean, s_sd, 0, 130), 1)
            heart_rate = int(_gauss_clamped(rng, hr_mean, hr_sd, 50, 140))
            stress = int(_gauss_clamped(rng, st_mean, st_sd, 1, 100))

            # Random-walk the position a little each tick.
            lat += rng.uniform(-0.004, 0.004)
            lon += rng.uniform(-0.004, 0.004)

            rows.append({
                "driver_id": drv["driver_id"],
                "driver_name": drv.get("name", drv["driver_id"]),
                "truck_id": drv["truck_id"],
                "timestamp": ts,
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "speed": speed,
                "fuel_level": rng.randint(15, 100),
                "heart_rate": heart_rate,
                "stress_score": stress,
                "risk_score": compute_risk_score(speed, stress, heart_rate),
            })

    return pd.DataFrame(rows)


def derive_gold(enriched: pd.DataFrame) -> GoldTables:
    """Build the three Gold tables from the enriched frame.

    Mirrors ``live_status_select_sql`` / ``safety_metrics_select_sql`` /
    ``safety_alerts_select_sql`` so the demo matches the real pipeline output.
    """
    df = enriched.sort_values("timestamp")

    # fleet_live_status — latest row per driver (ROW_NUMBER ... ORDER BY ts DESC).
    live = (
        df.sort_values("timestamp")
        .groupby("driver_id", as_index=False)
        .tail(1)
        .reset_index(drop=True)
        .sort_values("risk_score", ascending=False)
    )

    # driver_safety_metrics — hourly aggregates per driver.
    hourly = df.copy()
    hourly["hour_bucket"] = hourly["timestamp"].dt.floor("h")
    metrics = (
        hourly.groupby(["driver_id", "driver_name", "hour_bucket"], as_index=False)
        .agg(
            avg_heart_rate=("heart_rate", "mean"),
            max_speed=("speed", "max"),
            avg_stress=("stress_score", "mean"),
            avg_risk_score=("risk_score", "mean"),
            max_risk_score=("risk_score", "max"),
        )
        .round({"avg_heart_rate": 2, "avg_stress": 2, "avg_risk_score": 2})
        .sort_values(["driver_id", "hour_bucket"], ascending=[True, False])
    )

    # fleet_safety_alerts — every qualifying row (speed > 90 OR heart_rate > 90).
    alerts = df[(df["speed"] > 90) | (df["heart_rate"] > 90)].copy()
    alerts["alert_type"] = alerts.apply(
        lambda r: classify_alert(r["speed"], r["heart_rate"]), axis=1
    )
    alerts = alerts[[
        "timestamp", "driver_id", "driver_name", "truck_id", "speed",
        "heart_rate", "stress_score", "risk_score", "alert_type",
    ]].sort_values("timestamp", ascending=False).reset_index(drop=True)

    return GoldTables(
        live_status=live,
        safety_metrics=metrics,
        safety_alerts=alerts,
        enriched=df.reset_index(drop=True),
    )


# --------------------------------------------------------------------------- #
# Databricks SQL (live) source
# --------------------------------------------------------------------------- #

def databricks_config_present() -> bool:
    """True if the env vars needed for a live Databricks SQL read are set."""
    return all(
        os.getenv(k)
        for k in ("DATABRICKS_SERVER_HOSTNAME", "DATABRICKS_HTTP_PATH",
                  "DATABRICKS_TOKEN")
    )


def load_from_databricks(gold_catalog: str, gold_schema: str,
                         live_table: str = "fleet_live_status",
                         metrics_table: str = "driver_safety_metrics",
                         alerts_table: str = "fleet_safety_alerts") -> GoldTables:
    """Read the three Gold tables from a Databricks SQL Warehouse.

    Requires ``DATABRICKS_SERVER_HOSTNAME``, ``DATABRICKS_HTTP_PATH`` and
    ``DATABRICKS_TOKEN`` in the environment (or Streamlit secrets). The
    ``databricks-sql-connector`` dependency is imported lazily so demo mode has
    no hard dependency on it.
    """
    from databricks import sql  # lazy import — only needed in live mode

    fqn = lambda t: f"`{gold_catalog}`.`{gold_schema}`.`{t}`"  # noqa: E731
    with sql.connect(
        server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    ) as conn:
        live = pd.read_sql(f"SELECT * FROM {fqn(live_table)}", conn)
        metrics = pd.read_sql(f"SELECT * FROM {fqn(metrics_table)}", conn)
        alerts = pd.read_sql(f"SELECT * FROM {fqn(alerts_table)}", conn)

    # Decorate with driver names from the roster for nicer display.
    name_map = {d["driver_id"]: d.get("name", d["driver_id"]) for d in load_roster()}
    for frame in (live, metrics, alerts):
        if "driver_id" in frame.columns and "driver_name" not in frame.columns:
            frame["driver_name"] = frame["driver_id"].map(name_map)

    return GoldTables(
        live_status=live.sort_values("risk_score", ascending=False)
        if "risk_score" in live.columns else live,
        safety_metrics=metrics,
        safety_alerts=alerts,
        enriched=pd.DataFrame(),  # not reconstructable from Gold; drill-down uses metrics
    )
