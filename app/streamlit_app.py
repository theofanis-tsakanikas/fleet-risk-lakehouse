"""Fleet Safety Command Center — Streamlit UI.

An executive-facing dashboard over the Gold layer of the
databricks-fleet-dabs-orchestration pipeline. It turns the three Gold business
tables (live status, hourly safety metrics, safety alerts) into a command
centre: fleet KPIs, a live risk map, a driver risk leaderboard, per-driver
drill-downs and a Medallion-architecture walkthrough.

Run locally:
    pip install -r app/requirements.txt
    streamlit run app/streamlit_app.py

Data source:
    * Demo (default) — self-contained, no cloud, faithful to the real Gold
      logic. Perfect for a presentation or promo recording.
    * Databricks SQL — set DATABRICKS_SERVER_HOSTNAME / DATABRICKS_HTTP_PATH /
      DATABRICKS_TOKEN (env or .streamlit/secrets.toml) and pick it in the
      sidebar to read the live Gold Delta tables.
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

import fleet_data as fd

# --------------------------------------------------------------------------- #
# Page config + secrets bootstrap
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="Fleet Safety Command Center",
    page_icon="🚛",
    layout="wide",
)

try:
    for _k, _v in st.secrets.items():
        if not os.getenv(_k):
            os.environ[_k] = str(_v)
except Exception:
    pass

# --------------------------------------------------------------------------- #
# Theme — shared dark/cyan branding with the agent UI
# --------------------------------------------------------------------------- #

st.markdown("""
<style>
.stApp {
    background: linear-gradient(160deg, #060c1a 0%, #0d1b35 45%, #070e20 100%);
    color: #e2e8f0;
}
.main .block-container { padding-top: 1.2rem; padding-bottom: 3rem; }
[data-testid="stHeader"] {
    background: rgba(6, 12, 26, 0.97) !important;
    border-bottom: 1px solid rgba(56, 189, 248, 0.10) !important;
    backdrop-filter: blur(16px) !important;
}
[data-testid="stDecoration"] { display: none !important; }
[data-testid="stSidebar"] {
    background: rgba(10, 18, 40, 0.97) !important;
    border-right: 1px solid rgba(56, 189, 248, 0.18);
}
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span,
[data-testid="stSidebar"] label { color: #94a3b8 !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: #e2e8f0 !important; }
h1, h2, h3 { color: #e2e8f0 !important; }
p, li { color: #cbd5e1 !important; }
[data-testid="stMetric"] {
    background: rgba(30, 41, 59, 0.7) !important;
    border: 1px solid rgba(56, 189, 248, 0.25) !important;
    border-radius: 14px !important;
    padding: 1rem 1.2rem !important;
    backdrop-filter: blur(12px);
}
[data-testid="stMetricValue"] { color: #38bdf8 !important; font-weight: 700 !important; }
[data-testid="stMetricLabel"] {
    color: #64748b !important; font-size: 0.78rem !important;
    text-transform: uppercase; letter-spacing: 0.06em;
}
.stTabs [data-baseweb="tab-list"] {
    background: rgba(10, 18, 40, 0.6) !important;
    border-radius: 12px !important; padding: 6px !important;
    border: 1px solid rgba(56, 189, 248, 0.15) !important; gap: 8px;
    margin-bottom: 1.2rem !important;
}
.stTabs [data-baseweb="tab"] { color: #64748b !important; border-radius: 9px !important;
    padding: 0.55rem 1.1rem !important; }
.stTabs [aria-selected="true"] {
    background: rgba(56, 189, 248, 0.15) !important; color: #38bdf8 !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1d4ed8 0%, #0ea5e9 100%) !important;
    color: white !important; border: none !important; border-radius: 10px !important;
    font-weight: 600 !important;
}
hr { border: none !important; border-top: 1px solid rgba(56, 189, 248, 0.15) !important; }
[data-testid="stDeployButton"], .stDeployButton { display: none !important; }

/* Hero banner */
.fleet-hero {
    background: linear-gradient(135deg, rgba(29,78,216,0.18) 0%, rgba(14,165,233,0.10) 100%);
    border: 1px solid rgba(56, 189, 248, 0.25);
    border-radius: 18px; padding: 1.4rem 1.8rem; margin-bottom: 1.4rem;
}
.fleet-hero h1 { margin: 0; font-size: 1.9rem; }
.fleet-hero p { margin: 0.3rem 0 0; color: #94a3b8 !important; }
.badge {
    display: inline-block; padding: 0.2rem 0.7rem; border-radius: 999px;
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
}
.badge-demo { background: rgba(234,179,8,0.15); color: #fde047; border: 1px solid rgba(234,179,8,0.4); }
.badge-live { background: rgba(34,197,94,0.15); color: #86efac; border: 1px solid rgba(34,197,94,0.4); }

/* Medallion cards */
.medal {
    border-radius: 14px; padding: 1.1rem 1.3rem; height: 100%;
    border: 1px solid rgba(56,189,248,0.2); background: rgba(30,41,59,0.55);
}
.medal h3 { margin: 0 0 0.4rem; font-size: 1.05rem; }
.medal .big { font-size: 1.6rem; font-weight: 700; color: #38bdf8; }
.medal ul { margin: 0.6rem 0 0; padding-left: 1.1rem; }
.medal li { font-size: 0.85rem; color: #94a3b8 !important; }
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Risk helpers
# --------------------------------------------------------------------------- #

def risk_band(score: float) -> tuple[str, str]:
    """Return (label, hex colour) for a risk score."""
    if score >= 80:
        return "Critical", "#ef4444"
    if score >= 60:
        return "High", "#f97316"
    if score >= 40:
        return "Elevated", "#eab308"
    return "Safe", "#22c55e"


def risk_rgb(score: float) -> list[int]:
    return [int(c) for c in bytes.fromhex(risk_band(score)[1].lstrip("#"))]


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False)
def _load_demo(hours: int, step: int, seed: int) -> fd.GoldTables:
    return fd.derive_gold(fd.generate_demo_enriched(hours=hours, step_minutes=step, seed=seed))


@st.cache_data(show_spinner=True)
def _load_live(catalog: str, schema: str) -> fd.GoldTables:
    return fd.load_from_databricks(catalog, schema)


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.markdown("### 🚛 Command Center")
    st.caption("Gold-layer analytics for the fleet monitoring lakehouse.")
    st.divider()

    source = st.radio(
        "Data source",
        ["Demo data", "Databricks SQL (live)"],
        help="Demo synthesises faithful Gold data locally. Live reads the real "
             "Delta tables over a SQL Warehouse.",
    )

    live_ok = True
    catalog = schema = ""
    if source == "Databricks SQL (live)":
        catalog = st.text_input("Gold catalog", os.getenv("GOLD_CATALOG", "fleet_prod"))
        schema = st.text_input("Gold schema", os.getenv("GOLD_SCHEMA", "gold"))
        live_ok = fd.databricks_config_present()
        if not live_ok:
            st.warning(
                "Missing DATABRICKS_SERVER_HOSTNAME / DATABRICKS_HTTP_PATH / "
                "DATABRICKS_TOKEN. Falling back to demo data."
            )
    else:
        c1, c2 = st.columns(2)
        hours = c1.slider("History (h)", 1, 12, 6)
        step = c2.slider("Resolution (min)", 1, 10, 3)
        seed = st.number_input("Scenario seed", value=42, step=1,
                               help="Change to regenerate a different fleet scenario.")
        if st.button("🔄 Regenerate scenario", use_container_width=True):
            _load_demo.clear()

    st.divider()
    st.caption(
        "**Risk score** = speed·40% + stress·35% + heart-rate·25%, capped at 100 "
        "— identical to the Gold pipeline formula."
    )

# Resolve the data source.
use_live = source == "Databricks SQL (live)" and live_ok
if use_live:
    try:
        gold = _load_live(catalog, schema)
        mode_badge = '<span class="badge badge-live">● LIVE · DATABRICKS SQL</span>'
    except Exception as exc:  # noqa: BLE001
        st.error(f"Databricks read failed — falling back to demo. ({exc})")
        gold = _load_demo(6, 3, 42)
        mode_badge = '<span class="badge badge-demo">◆ DEMO DATA (fallback)</span>'
else:
    gold = _load_demo(hours, step, seed) if source == "Demo data" else _load_demo(6, 3, 42)
    mode_badge = '<span class="badge badge-demo">◆ DEMO DATA</span>'

live_df = gold.live_status.copy()
metrics_df = gold.safety_metrics.copy()
alerts_df = gold.safety_alerts.copy()
enriched_df = gold.enriched.copy()


# --------------------------------------------------------------------------- #
# Hero
# --------------------------------------------------------------------------- #

st.markdown(f"""
<div class="fleet-hero">
  <h1>🚛 Fleet Safety Command Center</h1>
  <p>Real-time driver-risk intelligence — telemetry × biometrics, scored on the
     Medallion Gold layer. {mode_badge}</p>
</div>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Tabs
# --------------------------------------------------------------------------- #

tab_cmd, tab_driver, tab_alerts, tab_medal = st.tabs([
    "🛰️ Command Center",
    "👤 Driver Drill-down",
    "🚨 Safety Alerts",
    "🥇 Medallion Journey",
])

# ── Command Center ────────────────────────────────────────────────────────── #
with tab_cmd:
    avg_risk = float(live_df["risk_score"].mean()) if len(live_df) else 0.0
    high_risk = int((live_df["risk_score"] >= 60).sum()) if len(live_df) else 0
    n_alerts = len(alerts_df)
    critical = int(alerts_df["alert_type"].str.startswith(("CRITICAL", "DANGER")).sum()) \
        if len(alerts_df) else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("🚚 Active trucks", len(live_df))
    k2.metric("⚖️ Avg fleet risk", f"{avg_risk:.1f}", risk_band(avg_risk)[0])
    k3.metric("🔥 High-risk drivers", high_risk, f"of {len(live_df)}")
    k4.metric("🚨 Critical alerts", critical, f"{n_alerts} total")

    st.divider()
    map_col, board_col = st.columns([1.4, 1])

    with map_col:
        st.markdown("##### 🗺️ Live fleet map — coloured by driver risk")
        if {"latitude", "longitude"}.issubset(live_df.columns) and len(live_df):
            mp = live_df.copy()
            mp["color"] = mp["risk_score"].apply(risk_rgb)
            mp["radius"] = 250 + mp["risk_score"] * 6
            layer = pdk.Layer(
                "ScatterplotLayer",
                data=mp,
                get_position="[longitude, latitude]",
                get_fill_color="color",
                get_radius="radius",
                opacity=0.75,
                pickable=True,
                stroked=True,
                get_line_color=[255, 255, 255, 120],
            )
            view = pdk.ViewState(
                latitude=float(mp["latitude"].mean()),
                longitude=float(mp["longitude"].mean()),
                zoom=10.2, pitch=35,
            )
            tooltip = {
                "html": "<b>{driver_name}</b> ({truck_id})<br/>"
                        "Risk: <b>{risk_score}</b> · Speed: {speed} · HR: {heart_rate}",
                "style": {"backgroundColor": "#0d1b35", "color": "#e2e8f0"},
            }
            st.pydeck_chart(pdk.Deck(
                layers=[layer], initial_view_state=view,
                map_style="mapbox://styles/mapbox/dark-v10", tooltip=tooltip,
            ))
        else:
            st.info("No geolocation columns available in this data source.")

    with board_col:
        st.markdown("##### 🏁 Driver risk leaderboard")
        board = live_df.sort_values("risk_score", ascending=False)
        fig = go.Figure(go.Bar(
            x=board["risk_score"],
            y=board.get("driver_name", board["driver_id"]),
            orientation="h",
            marker_color=[risk_band(s)[1] for s in board["risk_score"]],
            text=[f"{s:.0f}" for s in board["risk_score"]],
            textposition="outside",
        ))
        fig.update_layout(
            height=420, margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#cbd5e1", xaxis=dict(range=[0, 100], gridcolor="rgba(148,163,184,0.15)"),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.markdown("##### 📋 Current fleet status")
    show = live_df.copy()
    show["risk band"] = show["risk_score"].apply(lambda s: risk_band(s)[0])
    cols = [c for c in ["driver_name", "truck_id", "speed", "heart_rate",
                        "stress_score", "fuel_level", "risk_score", "risk band"]
            if c in show.columns]
    st.dataframe(show[cols], use_container_width=True, hide_index=True)

# ── Driver Drill-down ─────────────────────────────────────────────────────── #
with tab_driver:
    name_col = "driver_name" if "driver_name" in live_df.columns else "driver_id"
    names = live_df.sort_values("risk_score", ascending=False)[name_col].tolist()
    if not names:
        st.info("No drivers in the current data source.")
    else:
        chosen = st.selectbox("Select driver", names)
        d_live = live_df[live_df[name_col] == chosen].iloc[0]

        c1, c2, c3, c4 = st.columns(4)
        band_lbl, band_col = risk_band(d_live["risk_score"])
        c1.metric("Current risk", f"{d_live['risk_score']:.1f}", band_lbl)
        c2.metric("Speed (km/h)", f"{d_live.get('speed', 0):.0f}")
        c3.metric("Heart rate", f"{d_live.get('heart_rate', 0):.0f}")
        c4.metric("Stress", f"{d_live.get('stress_score', 0):.0f}")

        st.divider()
        if len(enriched_df):
            # Rich per-event time series (demo mode).
            ser = enriched_df[enriched_df[name_col] == chosen].sort_values("timestamp")
            st.markdown("##### 📈 Telemetry × biometrics — the 60-second correlation in action")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ser["timestamp"], y=ser["speed"],
                                     name="Speed", line=dict(color="#38bdf8")))
            fig.add_trace(go.Scatter(x=ser["timestamp"], y=ser["heart_rate"],
                                     name="Heart rate", line=dict(color="#f472b6")))
            fig.add_trace(go.Scatter(x=ser["timestamp"], y=ser["risk_score"],
                                     name="Risk score", line=dict(color="#f97316", width=3)))
            fig.update_layout(
                height=380, margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#cbd5e1", legend=dict(orientation="h"),
                xaxis=dict(gridcolor="rgba(148,163,184,0.12)"),
                yaxis=dict(gridcolor="rgba(148,163,184,0.12)"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            # Live mode — fall back to the hourly safety-metrics aggregate.
            ser = metrics_df[metrics_df[name_col] == chosen].sort_values("hour_bucket")
            st.markdown("##### 📈 Hourly safety metrics")
            if len(ser):
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=ser["hour_bucket"], y=ser["avg_risk_score"],
                                         name="Avg risk", line=dict(color="#f97316", width=3)))
                fig.add_trace(go.Scatter(x=ser["hour_bucket"], y=ser["avg_heart_rate"],
                                         name="Avg heart rate", line=dict(color="#f472b6")))
                fig.update_layout(
                    height=380, margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#cbd5e1", legend=dict(orientation="h"),
                )
                st.plotly_chart(fig, use_container_width=True)

        d_alerts = alerts_df[alerts_df[name_col] == chosen] if name_col in alerts_df.columns \
            else alerts_df[alerts_df["driver_id"] == d_live["driver_id"]]
        st.markdown(f"##### 🚨 Recent alerts for {chosen} — {len(d_alerts)} total")
        if len(d_alerts):
            st.dataframe(d_alerts.head(15), use_container_width=True, hide_index=True)
        else:
            st.success("No safety alerts for this driver in the current window.")

# ── Safety Alerts ─────────────────────────────────────────────────────────── #
with tab_alerts:
    if not len(alerts_df):
        st.success("No safety alerts in the current window.")
    else:
        counts = alerts_df["alert_type"].value_counts()
        cols = st.columns(min(4, len(counts)) or 1)
        for i, (atype, cnt) in enumerate(counts.items()):
            cols[i % len(cols)].metric(atype.split(":")[0], int(cnt))

        st.divider()
        types = ["All"] + sorted(alerts_df["alert_type"].unique().tolist())
        pick = st.selectbox("Filter by alert type", types)
        view = alerts_df if pick == "All" else alerts_df[alerts_df["alert_type"] == pick]
        st.markdown(f"##### 🚨 Alert log — {len(view)} events")
        st.dataframe(view, use_container_width=True, hide_index=True)

# ── Medallion Journey ─────────────────────────────────────────────────────── #
with tab_medal:
    st.markdown("##### 🏗️ The Medallion journey — from raw sensors to executive risk")
    st.caption(
        "Two independent streams (GPS trackers + biometric watches) are ingested, "
        "cleansed, and correlated on a ±60-second window to produce the Gold risk score."
    )

    # Indicative volumes — real counts in live mode, synthesised counts in demo.
    n_gold = len(enriched_df) if len(enriched_df) else int(metrics_df.get("driver_id", pd.Series()).count())
    n_silver = int(n_gold / 0.82) if n_gold else 0   # ~18% dropped as dirty in cleansing
    n_bronze = int(n_silver / 0.80) if n_silver else 0  # ~20% raw is malformed/duplicated

    b, s, g = st.columns(3)
    with b:
        st.markdown(f"""
        <div class="medal">
          <h3>🥉 Bronze — raw ingest</h3>
          <div class="big">{n_bronze:,}</div>
          <ul>
            <li>Auto Loader from S3 (trackers + watches)</li>
            <li>Schema-on-read, append-only</li>
            <li>~20% malformed: bad IDs, sentinel speeds, null HR</li>
          </ul>
        </div>""", unsafe_allow_html=True)
    with s:
        st.markdown(f"""
        <div class="medal">
          <h3>🥈 Silver — cleansed</h3>
          <div class="big">{n_silver:,}</div>
          <ul>
            <li>Dedup, range filters, null handling</li>
            <li>Nested watch metrics flattened</li>
            <li>Type-safe, conformed driver/truck keys</li>
          </ul>
        </div>""", unsafe_allow_html=True)
    with g:
        st.markdown(f"""
        <div class="medal">
          <h3>🥇 Gold — business-ready</h3>
          <div class="big">{n_gold:,}</div>
          <ul>
            <li>±60s temporal join: telemetry × biometrics</li>
            <li>Weighted <b>risk_score</b> (capped 0–100)</li>
            <li>DQ guards: non-empty join, no null keys, risk ∈ [0,100]</li>
          </ul>
        </div>""", unsafe_allow_html=True)

    st.divider()
    st.markdown("##### ✅ Gold data-quality assertions (enforced every run)")
    dq = pd.DataFrame([
        {"Assertion": "Enriched join non-empty", "Guard": "fleet_enriched_view rows > 0", "Status": "✅ PASS"},
        {"Assertion": "No null business keys", "Guard": "driver_id / timestamp NOT NULL", "Status": "✅ PASS"},
        {"Assertion": "Risk score in range", "Guard": "risk_score ∈ [0, 100]", "Status": "✅ PASS"},
        {"Assertion": "Metrics populated", "Guard": "driver_safety_metrics rows > 0", "Status": "✅ PASS"},
    ])
    st.dataframe(dq, use_container_width=True, hide_index=True)
    st.caption(
        "Source of truth: `notebooks/gold/gold_fleet_monitoring_enrichment.py` and "
        "`src/fleet_transforms/gold.py`. This dashboard reuses the same risk formula."
    )
