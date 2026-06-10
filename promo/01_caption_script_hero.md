# Hero Promo — Caption Script (exact words + timings)

**Target:** ~70s · captions + music, no voiceover · captions in English.
**Hero asset:** the **Fleet Safety Command Center** (`app/streamlit_app.py`) in **demo mode**.
Supporting footage: the repo (DABs/Terraform/Actions) + `images/grafana_dashboards.png`.

Caption style: large, lower-third, white text with a cyan accent on the key word, dark
semi-transparent backing. 2.5–4s on screen. One line per beat.

---

### SCENE 0 — Hook (0:00–0:06)
- **Screen:** Black → title card on the dark gradient. 1.5s flash: a route/truck motif → the risk map igniting with coloured dots.
- **Caption (0:02):** `What if your fleet told you who's about to crash —`
- **Caption (0:04):** `— before it happens?`
- **Music:** soft swell from the title card.

### SCENE 1 — The command center (0:06–0:20)
- **Screen:** Command Center tab. KPI row reads (Active trucks · Avg fleet risk · High-risk drivers · Critical alerts). Slow push-in on the **risk map**; hover a red (Critical) truck → tooltip shows driver, risk, speed, HR.
- **Caption (0:08):** `Live driver-risk scoring across the fleet.`
- **Caption (0:15):** `GPS telemetry × heart-rate — scored every minute.`

### SCENE 2 — The correlation (0:20–0:34)
- **Screen:** Pan to the **leaderboard** (drivers ranked by risk). Click the top driver → **Driver Drill-down**: the chart with Speed, Heart-rate and Risk lines; the risk line spikes where speed + HR rise together.
- **Caption (0:22):** `Rank every driver by risk.`
- **Caption (0:28):** `Speed and stress, correlated on a ±60-second window.`

### SCENE 3 — The engineering (0:34–0:48)
- **Screen:** **Medallion Journey** tab. The three cards (Bronze → Silver → Gold) with their counts; then the **data-quality assertions** table (all ✅).
- **Caption (0:36):** `Bronze → Silver → Gold, on Apache Spark.`
- **Caption (0:42):** `~20% dirty sensor data cleaned out — quality gated every run.`

### SCENE 4 — Production proof (0:48–0:60)
- **Screen:** Quick cuts in the repo: `databricks.yml` (the bundle) → the three `terraform/` layers → a **green GitHub Actions** run → `images/grafana_dashboards.png` (the exec dashboard).
- **Caption (0:50):** `Provisioned as code — three Terraform layers, Databricks Asset Bundles.`
- **Caption (0:56):** `Unity Catalog governed. Shipped by CI/CD.`

### SCENE 5 — Close (0:60–0:70)
- **Screen:** End card (dark). Project name + value line + your name / GitHub. Music resolves.
- **Caption (static):**
  > **Real-Time IoT Fleet Safety — Databricks Lakehouse**
  > Medallion architecture · live risk scoring · IaC + CI/CD
  > *<your name> — github.com/<you>*

---

## Caption master list (copy-paste ready)
```
1.  What if your fleet told you who's about to crash —
2.  — before it happens?
3.  Live driver-risk scoring across the fleet.
4.  GPS telemetry × heart-rate — scored every minute.
5.  Rank every driver by risk.
6.  Speed and stress, correlated on a ±60-second window.
7.  Bronze → Silver → Gold, on Apache Spark.
8.  ~20% dirty sensor data cleaned out — quality gated every run.
9.  Provisioned as code — three Terraform layers, Databricks Asset Bundles.
10. Unity Catalog governed. Shipped by CI/CD.
11. [End card] Real-time fleet safety on Databricks — IaC, end to end.
```

## Notes
- The `risk_score` weighting (speed 40% · stress 35% · heart-rate 25%, capped at 100) is real —
  it lives in `src/fleet_transforms/gold.py`. You can add it as a small on-screen formula card in
  scene 2 if you want the "real model" signal.
- Keep the **"◆ DEMO DATA"** badge visible in scenes 1–3. It's honest and reads as "live product".
- If you tighten to ~60s, merge scenes 4 captions into one (`Provisioned as code. Governed. Shipped by CI/CD.`).
