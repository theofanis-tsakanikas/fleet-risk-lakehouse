# Hero Promo — Shot List (record this, in this order)

Record **clips**, then assemble in the edit (clip order ≠ final scene order). The Command Center
runs in demo mode, so every clip is repeatable until you get a clean take.

## Stage 0 — Setup (before any recording)
1. Launch the Command Center:
   ```
   cd app && python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   streamlit run streamlit_app.py
   ```
2. In the sidebar: **Demo data**, History `6h`, Resolution `3 min`. Try a couple of **seeds** until
   the leaderboard has 1–2 clearly **Critical** drivers and a spread (seed `42` is a good default).
3. Confirm: dark theme, **no** Streamlit "Deploy" button, **"◆ DEMO DATA"** badge visible.
4. Open a second window with the repo for the IaC montage: `databricks.yml`, `terraform/`, the
   Actions tab (a green run), `images/grafana_dashboards.png`.
5. Screen Studio: 16:9, retina, clean menu bar, browser zoom so captions don't fight the UI.

---

## Clips to record (in this recording order)

### CLIP A — Command Center hero (record first; it's the opener)
- **What:** Land on the **Command Center** tab. Let the KPI row read, then a slow push-in on the
  **risk map**. Hover a **red (Critical)** truck so the tooltip shows driver / risk / speed / HR.
- **Length:** ~14s raw (use ~12s).
- **Screen Studio:** gentle auto-zoom into the map; smooth cursor; one motion at a time.

### CLIP B — Leaderboard → drill-down (the clever bit)
- **What:** Pan to the **risk leaderboard**. Click the **top driver** → go to **Driver Drill-down**.
  Let the **Speed / Heart-rate / Risk** chart draw; pause where the risk line spikes.
- **Length:** ~16s raw.
- **Screen Studio:** auto-zoom on the clicked driver, ease out to the full time-series.

### CLIP C — Medallion + data quality
- **What:** **Medallion Journey** tab. Slow pan across the Bronze/Silver/Gold cards (the counts),
  then the **DQ assertions** table (all ✅).
- **Length:** ~12s raw.

### CLIP D — IaC + CI/CD montage (in the repo / browser)
- **What:** 2–3s each: `databricks.yml` (scroll the bundle vars), the `terraform/` layer folders,
  a **green GitHub Actions** run, and `images/grafana_dashboards.png`.
- **Length:** ~12s raw (→ ~8s montage).
- **Note:** A clean screenshot is fine for any of these.

### CLIP E — Safety alerts (OPTIONAL b-roll)
- **What:** The **Safety Alerts** tab — the alert-type KPIs + the filtered log. Good filler if a
  scene runs short.
- **Length:** ~8s raw.

### Title + End cards
- Built in the editor. Text from `01_caption_script_hero.md` (scenes 0 and 5).

---

## Assembly order (in the editor) = final scenes
`Title → CLIP A → CLIP B → CLIP C → CLIP D → End card`
Map to the script: 0 → 1 → 2 → 3 → 4 → 5.

---

## Screen Studio tips
- **Auto-zoom on clicks** focuses attention on the map dot, the leaderboard bar, the risk spike.
- Keep the **"◆ DEMO DATA"** badge in frame for scenes 1–3.
- **One motion per beat** — don't zoom + pan + cut at once.
- **Captions** lower-third so they never cover the map or chart.
- **Music:** calm tech/ambient bed, low; resolve cleanly on the end card.
- Export **1080p (or 4K) MP4, 30–60fps**; keep a captioned + a no-caption master.

## Final QC before you publish
- [ ] Reads on **mute** (the one-line test from `00_master_plan.md`).
- [ ] The **"demo data"** label is visible whenever synthetic data is shown.
- [ ] No tracebacks, empty states, or dead waits on screen.
- [ ] Under ~75s.
- [ ] Ends with a clear "what is this + who made it" card.
