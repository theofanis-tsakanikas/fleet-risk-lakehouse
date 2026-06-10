# Promo Video — Master Plan (Fleet Safety Lakehouse)

## Goal & audience
A LinkedIn / portfolio piece. A recruiter, data leader or engineer must grasp in **~15 seconds**:
> *Raw GPS telemetry + driver biometrics → a live driver-risk score, on a governed Databricks lakehouse — built and shipped as Infrastructure-as-Code.*

The video sells the **business outcome** (proactive fleet safety) and *proves* it with the
engineering underneath (Medallion architecture, a real risk model, CI/CD, governance).

## Two deliverables
| | Hero promo | Deep-dive |
|---|---|---|
| Length | **~60–75s** | **~3–4 min** |
| Audio | Captions + light music, **no voiceover** | **Voiceover** + captions |
| Use | Lead with it on LinkedIn / top of the repo | "Watch the full walkthrough" for technical viewers |
| Plan | this file + `01_caption_script_hero.md` + `02_shot_list.md` | `04_deep_dive_plan.md` |

## The hero asset
The **Fleet Safety Command Center** (`app/streamlit_app.py`) is the star — it turns the three
Gold tables into something a CEO understands at a glance: a live risk map, a driver leaderboard,
a per-driver drill-down, and the Medallion journey. **Record it in demo mode** (no Databricks
cluster, no cost — see `03_demo_recipe.md`); the numbers are faithful to the real pipeline.

## 4 principles
1. **Outcome first.** Open on the risk map + leaderboard, not on architecture. The "so what" is *fleet safety*.
2. **Muted-friendly.** Autoplay-muted is the norm → the story must read without sound. One caption per beat.
3. **Show, don't explain.** Motion = the map populating, a driver's risk line spiking, the medallion counts.
4. **Honest.** Demo data is *labelled* as demo; the risk formula and DQ gates are the real ones. Don't imply a live fleet you don't have.

## Structure — Hero (~70s, 6 scenes)
| # | Time | On screen | Caption |
|---|------|-----------|---------|
| 0 | 0–6s | Title card (dark) → fast flash: a truck/route + the risk map lighting up | *What if your fleet told you who's about to have an accident?* |
| 1 | 6–20s | Command Center: KPIs + risk map of trucks coloured by risk; hover a high-risk truck | *Live driver-risk scoring — GPS telemetry × heart-rate, every minute.* |
| 2 | 20–34s | Driver leaderboard → click a high-risk driver → drill-down chart (speed × HR × risk) | *Speed and stress, correlated on a ±60-second window.* |
| 3 | 34–48s | Medallion Journey tab: Bronze → Silver → Gold counts + the DQ assertions table | *Bronze → Silver → Gold. ~20% dirty sensor data cleaned out, every run.* |
| 4 | 48–60s | Quick cuts: `databricks.yml` / Terraform layers / GitHub Actions green check / Grafana | *Provisioned as code. Unity Catalog governed. CI/CD shipped.* |
| 5 | 60–70s | End card: project name + value line + your name / GitHub | *Real-time fleet safety on Databricks — IaC, end to end.* |

## Non-negotiables (the video must contain)
- The **risk map** + **leaderboard** (the outcome, the hook)
- The **drill-down** that visualises the **telemetry × biometrics correlation** (the clever bit)
- The **Medallion** story + **data-quality** gates (the engineering rigour)
- A flash of **IaC + CI/CD** (Terraform layers, DABs, GitHub Actions) — proves it's production, not a notebook
- A clear **"demo data"** label whenever synthetic data is on screen (honesty)

## Pre-production checklist (do BEFORE recording)
- [ ] `cd app && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- [ ] `streamlit run streamlit_app.py` → confirm dark theme, no Deploy button, **"◆ DEMO DATA"** badge visible.
- [ ] Pick a **seed** in the sidebar that gives a punchy leaderboard (a couple of clearly Critical drivers). `42` is a good default.
- [ ] Have the repo open in a second tab/window for the IaC montage (scene 4): `databricks.yml`, `terraform/`, a green Actions run, `images/grafana_dashboards.png`.
- [ ] Screen Studio: 16:9, retina, clean menu bar, comfortable zoom.

## Honest do / don't
- **DO** keep the "demo data" badge on screen in scenes 1–3 — it's honest *and* it reads as "interactive product".
- **DO** show the real `risk_score` formula caption (40% speed / 35% stress / 25% heart-rate) — it signals you built a real model, not a random number.
- **DON'T** imply this is monitoring a live, real fleet. Frame it as *"the analytics layer of a fleet-safety lakehouse."*
- **DON'T** show a Databricks bill or live cluster spin-up waits — demo mode avoids both.

## The one-line test
If a stranger watches the **first 10 seconds on mute** and says *"it scores how risky each driver is, live"* — the opening works.
