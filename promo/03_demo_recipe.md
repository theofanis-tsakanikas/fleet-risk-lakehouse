# Promo Demo — Recipe (how to make the Command Center look great on camera)

The hero is recorded entirely from the **Fleet Safety Command Center** in **demo mode** — no
Databricks workspace, no cluster, no cost. The data is synthetic but **faithful**: the risk score
and alert thresholds are the exact ones the Gold pipeline uses.

## TL;DR
| Choice | Value | Why |
|---|---|---|
| **Mode** | **Demo data** | Zero cost, fully repeatable, runs offline. |
| **Seed** | **42** (try a few) | Gives a punchy leaderboard with 1–2 Critical drivers. |
| **History / resolution** | **6h / 3 min** | Smooth drill-down lines without clutter. |
| **Result shot** | the in-app tabs + `images/grafana_dashboards.png` | The dashboard image is the "executive" payoff. |

## Run it
```
cd app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```
Open http://localhost:8501. Sidebar → **Demo data**. Adjust the **seed** until the leaderboard
reads well (a couple of red/Critical drivers, a clear spread). Re-roll with **🔄 Regenerate scenario**.

## What's real vs synthesised (so your captions stay honest)
- **Real:** the `risk_score` formula (speed 40% · stress 35% · heart-rate 25%, capped 100) and the
  alert classes (`CRITICAL / DANGER / WARNING / OVERSPEED`) — both mirror `src/fleet_transforms/gold.py`.
  The driver roster is the project's real `src/mock_generator/fleet_config.json` (Athens area).
- **Synthesised:** the per-minute telemetry/biometric values (so it runs without a cluster).
- **Caption honesty:** keep the **"◆ DEMO DATA"** badge on screen. Frame it as *"the analytics layer
  of the fleet-safety lakehouse"*, not a live production fleet.

## Optional — live mode (only if you want a "real Databricks" beat)
If you have the bundle deployed and a SQL Warehouse with the Gold tables populated:
```
export DATABRICKS_SERVER_HOSTNAME=dbc-xxxx.cloud.databricks.com
export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/xxxxxxxx
export DATABRICKS_TOKEN=dapi...
export GOLD_CATALOG=fleet_prod GOLD_SCHEMA=gold
```
Then pick **"Databricks SQL (live)"** in the sidebar and the badge flips to **"● LIVE · DATABRICKS SQL"**.
Not required for the hero — demo mode looks identical and costs nothing.

## IaC / CI-CD montage assets (scene 4)
No deployment needed — just open these in the repo for the montage:
- `databricks.yml` — the Databricks Asset Bundle (catalogs, schemas, volumes, jobs).
- `terraform/` — the three layered Terraform stacks (foundation / workspace / governance).
- **GitHub → Actions** — point at a green `deploy-fleet-pipeline` or `ci` run.
- `images/grafana_dashboards.png` — the executive observability dashboard.
- `docs/adr/` — the ADRs (ADR-002 temporal join, ADR-003 SQL-Warehouse-Grafana) make great pause frames.

## After the shoot
Nothing to tear down for demo mode. If you used live mode, just stop your SQL Warehouse if it
auto-started.
