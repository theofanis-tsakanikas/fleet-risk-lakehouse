# 🚛 Fleet Safety Command Center

An executive-facing **Streamlit** dashboard over the Gold layer of this
pipeline. It turns the three Gold business tables into a live command centre:
fleet KPIs, a risk-coloured map, a driver risk leaderboard, per-driver
drill-downs, a safety-alert log, and a Medallion-architecture walkthrough.

It shares the dark/cyan branding of the `multi-cloud-self-healing-agent` UI so
the portfolio reads as one coherent product suite.

> Built for presentations & promo recordings: it runs **fully offline** in demo
> mode — no Databricks cluster, no cloud credentials, no cost.

---

## Quick start (demo mode)

```bash
cd app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Open http://localhost:8501. Demo mode is the default — use the sidebar to change
the history window / resolution or **regenerate** a different fleet scenario
(via the seed).

## Live mode (Databricks SQL)

Reads the real Gold Delta tables over a serverless SQL Warehouse. Provide
credentials via environment variables or `.streamlit/secrets.toml`:

```toml
# app/.streamlit/secrets.toml   (git-ignored)
DATABRICKS_SERVER_HOSTNAME = "dbc-xxxx.cloud.databricks.com"
DATABRICKS_HTTP_PATH       = "/sql/1.0/warehouses/xxxxxxxx"
DATABRICKS_TOKEN           = "dapi..."
GOLD_CATALOG               = "fleet_prod"
GOLD_SCHEMA                = "gold"
```

Then pick **"Databricks SQL (live)"** in the sidebar. If credentials are
missing, the app warns and falls back to demo data.

---

## How faithful is the demo?

The risk score and alert classification in [`fleet_data.py`](fleet_data.py) are
**byte-for-byte identical** to the Spark SQL in
[`src/fleet_transforms/gold.py`](../src/fleet_transforms/gold.py):

```
risk_score = LEAST(100, speed/120·40 + stress/100·35 + heart_rate/110·25)
```

The driver roster is loaded from the project's real
[`fleet_config.json`](../src/mock_generator/fleet_config.json), and the three
Gold tables are derived with the same latest-per-driver / hourly-aggregate /
alert-threshold logic the pipeline uses. The demo shows the numbers the real
pipeline *would* write — it is faithful, not invented.

## Files

| File | Purpose |
|---|---|
| `streamlit_app.py` | UI: tabs, KPIs, map, leaderboard, drill-down, Medallion view |
| `fleet_data.py` | Data layer: demo synthesis + Databricks SQL reader (one interface) |
| `requirements.txt` | UI dependencies (light; no Spark) |
| `.streamlit/config.toml` | Dark/cyan theme matching the agent UI |
