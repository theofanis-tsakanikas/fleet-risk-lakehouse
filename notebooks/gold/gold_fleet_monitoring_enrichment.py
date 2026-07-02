# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # 🏆 Fleet Monitoring Gold Layer
# MAGIC This notebook performs the final data enrichment by joining Trackers and Watches.
# MAGIC It uses a hybrid configuration to support both Local and Databricks environments.
# MAGIC
# MAGIC Beyond the enriched tables it now also: runs a **declarative data-quality suite**
# MAGIC (quarantining bad rows instead of crashing blind), emits **pipeline self-metrics**,
# MAGIC checks the risk-score distribution for **drift**, and enforces **column masks** on the
# MAGIC special-category biometric + location columns. All of that logic is imported from the
# MAGIC pure, unit-tested modules under `src/` — the notebook only orchestrates.

# COMMAND ----------
import os
import logging
import sys
from datetime import datetime

from pyspark.sql.functions import lit

# --- LOGGER CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- DIRECTORY CONFIGURATION ---
if "__file__" in locals() or "__file__" in globals():
    current_dir = os.path.dirname(os.path.abspath(__file__))
else:
    current_dir = os.getcwd()

# --- IMPORTABLE GOLD LOGIC ---
# The risk_score / temporal-join / dedup SQL, the DQ suite, observability, drift, and
# masking builders all live in pure, unit-tested modules under src/. The bundle ships src/
# to the workspace; add it to sys.path. A wrong path surfaces loudly as an ImportError.
_SRC = os.path.abspath(os.path.join(current_dir, "..", "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
from fleet_transforms.gold import (  # noqa: E402
    check_enriched_not_empty,
    enriched_view_select_sql,
    live_status_expectations,
    live_status_select_sql,
    safety_alerts_select_sql,
    safety_metrics_select_sql,
)
from fleet_transforms.quality import enforce, evaluate, split  # noqa: E402
from fleet_transforms.observability import (  # noqa: E402
    METRICS_SCHEMA_DDL,
    match_rate,
    metric_rows,
    null_rate_select_sql,
)
from fleet_transforms.drift import (  # noqa: E402
    DEFAULT_BASELINE,
    assess_drift,
    band_counts_select_sql,
)
from fleet_governance.masking import (  # noqa: E402
    apply_mask_ddls,
    drop_mask_ddls,
    mask_function_ddls,
)

# --- HYBRID CONFIGURATION (Local .env support) ---
try:
    from dotenv import load_dotenv

    dotenv_path = os.path.join(current_dir, "../../.env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
        logger.info("Loaded local .env file")
except ImportError:
    pass

# --- INITIALIZE SPARK ---
if "spark" not in globals():
    # For local development (e.g VS Code / Databricks Connect)
    logger.info("Connecting to Databricks Serverless Compute (Local Context)...")
    from databricks.connect import DatabricksSession

    spark = DatabricksSession.builder.serverless().getOrCreate()
else:
    # This runs inside Databricks (Jobs / Notebooks)
    # It uses the existing session that is UC-Ready
    logger.info("✅ Using existing Databricks Spark session")


# --- SAFE PARAMETER RETRIEVAL ---
def get_param(name):
    """
    Helper to get parameters from Databricks Widgets
    with fallback to Environment Variables (for local development).

    This approach ensures the code is environment-agnostic.
    """
    # 1. Check if running in a Databricks environment by looking for dbutils in globals
    if "dbutils" in globals():
        try:
            # Attempt to retrieve the value from Databricks Widgets
            return dbutils.widgets.get(name)
        except Exception:
            # If widget is not defined, fall back to environment variables
            pass

    # 2. Fallback to Environment Variables (Local Dev or Cluster Env Vars)
    val = os.environ.get(name)

    if not val:
        logger.error(f"Missing parameter: {name}")
        raise KeyError(
            f"Parameter '{name}' not found in Databricks widgets or system environment variables."
        )

    return val


def get_param_or(name, default):
    """Optional parameter: widget/env value if present, else ``default``."""
    if "dbutils" in globals():
        try:
            return dbutils.widgets.get(name)
        except Exception:
            pass
    return os.environ.get(name, default)


def get_run_id():
    """A stable identifier for this pipeline run (job run id in Databricks, else local stamp)."""
    try:
        run_id = spark.conf.get("spark.databricks.job.runId")
        if run_id:
            return run_id
    except Exception:
        pass
    return datetime.now().strftime("local-%Y%m%d%H%M%S")


# === CONFIGURATION SETUP ===
try:
    gold_catalog = get_param("GOLD_CATALOG")
    gold_schema = get_param("GOLD_SCHEMA")
    gold_live_table = get_param("GOLD_LIVE_TABLE")
    gold_metrics_table = get_param("GOLD_METRICS_TABLE")
    gold_alerts_table = get_param("GOLD_ALERTS_TABLE")
    gold_metadata_schema = get_param("GOLD_METADATA_SCHEMA")

    # Group whose members see UNMASKED biometric / precise-location values.
    mask_privileged_group = get_param_or(
        "MASK_PRIVILEGED_GROUP", "fleet_safety_officers"
    )

    # Source Tables (Silver)
    w_silver_path = f"{get_param('WATCHES_CATALOG')}.{get_param('WATCHES_SILVER_SCHEMA')}.{get_param('WATCHES_SILVER_TABLE')}"
    t_silver_path = f"{get_param('TRACKERS_CATALOG')}.{get_param('TRACKERS_SILVER_SCHEMA')}.{get_param('TRACKERS_SILVER_TABLE')}"

    # Target Tables (Gold)
    live_status_table = f"{gold_catalog}.{gold_schema}.{gold_live_table}"
    safety_metrics_table = f"{gold_catalog}.{gold_schema}.{gold_metrics_table}"
    safety_alerts_table = f"{gold_catalog}.{gold_schema}.{gold_alerts_table}"
    live_quarantine_table = f"{gold_catalog}.{gold_schema}.{gold_live_table}_quarantine"

    # Observability fact (tall metrics) lives in the metadata schema.
    function_schema = f"{gold_catalog}.{gold_schema}"
    metrics_fact_table = f"{gold_catalog}.{gold_metadata_schema}.pipeline_metrics"

except KeyError as e:
    logger.error(f"Configuration error: {e}")
    raise

run_id = get_run_id()
captured_at = datetime.now()
measures = {}  # accumulates pipeline self-metrics, flushed at the end

# COMMAND ----------
# MAGIC %md
# MAGIC ### 1. Unified Enriched View (Temporal Join)
# MAGIC We use a 1-minute interval to sync asynchronous Tracker and Watch events.

# COMMAND ----------
logger.info("Creating enriched temporary view...")
spark.sql(f"USE CATALOG {gold_catalog}")
spark.sql(f"USE SCHEMA {gold_schema}")

logger.info(f"Context locked to {gold_catalog}. Ready for JOIN.")

spark.sql(
    "CREATE OR REPLACE TEMPORARY VIEW fleet_enriched_view AS"
    + enriched_view_select_sql(t_silver_path, w_silver_path)
)

# COMMAND ----------
# --- DATA QUALITY: enriched view must not be empty ---
# An INNER JOIN with zero matches means the ±60s window found no correlated events.
# This is always a pipeline problem (timestamp skew, empty Silver tables) — not a
# valid business state — so we raise immediately rather than silently writing empty tables.
view_count = spark.sql("SELECT COUNT(*) AS cnt FROM fleet_enriched_view").collect()[0][
    "cnt"
]
check_enriched_not_empty(view_count)
logger.info(f"DQ passed: fleet_enriched_view contains {view_count:,} rows.")
measures["enriched_rows"] = view_count

# --- OBSERVABILITY: join match rate (early-warning for stream timestamp skew) ---
watch_drivers = spark.sql(
    f"SELECT COUNT(DISTINCT user_id) AS c FROM {w_silver_path}"
).collect()[0]["c"]
matched_drivers = spark.sql(
    "SELECT COUNT(DISTINCT driver_id) AS c FROM fleet_enriched_view"
).collect()[0]["c"]
measures["watch_drivers"] = watch_drivers
measures["matched_drivers"] = matched_drivers
measures["join_match_rate"] = match_rate(matched_drivers, watch_drivers)
logger.info(
    f"Join match rate: {measures['join_match_rate']:.2%} ({matched_drivers}/{watch_drivers} watch drivers matched)."
)

# COMMAND ----------
# MAGIC %md
# MAGIC ### 2. Production Gold Tables + Declarative Data Quality
# MAGIC Writing the business-ready tables. `fleet_live_status` is validated against a
# MAGIC declarative expectation suite (built from the risk model); rows that violate an
# MAGIC ERROR expectation are quarantined to a side table, and the run fails only if any
# MAGIC ERROR expectation was breached — bad data is captured, not silently dropped.

# COMMAND ----------
logger.info(f"Updating Gold Tables in {gold_catalog}.{gold_schema}...")

# Build the candidate live-status set as a DataFrame so the DQ suite can split it.
live_candidate = spark.sql(live_status_select_sql("fleet_enriched_view"))

suite = live_status_expectations()
results = evaluate(live_candidate, suite)
valid_df, quarantine_df = split(live_candidate, suite)

for r in results:
    level = logging.INFO if r.passed else logging.WARNING
    logger.log(
        level,
        f"DQ [{r.expectation.severity.value}] {r.expectation.name}: {r.failed}/{r.total} violated.",
    )

quarantined = quarantine_df.count()
measures["live_quarantined_rows"] = quarantined
if quarantined > 0:
    (
        quarantine_df.withColumn("_dq_run_id", lit(run_id))
        .write.mode("append")
        .option("mergeSchema", "true")
        .saveAsTable(live_quarantine_table)
    )
    logger.warning(f"Quarantined {quarantined} row(s) to {live_quarantine_table}.")

# Persist only the validated rows as the production table.
valid_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    live_status_table
)
measures["live_status_rows"] = valid_df.count()

# Fail the run if (and only if) an ERROR expectation was breached.
enforce(results)
logger.info(f"DQ passed: {live_status_table} satisfies all ERROR expectations.")

# COMMAND ----------
# Table 2: Hourly Safety Metrics (Aggregated)
spark.sql(
    f"CREATE OR REPLACE TABLE {safety_metrics_table} AS"
    + safety_metrics_select_sql("fleet_enriched_view")
)

metrics_count = spark.sql(
    f"SELECT COUNT(*) AS cnt FROM {safety_metrics_table}"
).collect()[0]["cnt"]
if metrics_count == 0:
    raise ValueError(
        f"Gold DQ FAILED: {safety_metrics_table} has 0 rows. Unexpected given enriched view passed the non-empty check."
    )
measures["safety_metrics_rows"] = metrics_count
logger.info(f"DQ passed: {safety_metrics_table} contains {metrics_count:,} rows.")

# Table 3: Safety Alerts (Historical Log)
# risk_score is included so Grafana alert panels can threshold on a single numeric column.
spark.sql(
    f"CREATE OR REPLACE TABLE {safety_alerts_table} AS"
    + safety_alerts_select_sql("fleet_enriched_view")
)
measures["safety_alerts_rows"] = spark.sql(
    f"SELECT COUNT(*) AS cnt FROM {safety_alerts_table}"
).collect()[0]["cnt"]

# --- OBSERVABILITY: sensor null rates on the live table ---
# A wearable feed going dark shows up as a rising null rate on the dashboard,
# not as a quietly degraded risk score (COALESCE would hide it).
null_row = (
    spark.sql(
        null_rate_select_sql(live_status_table, ["heart_rate", "stress_score", "speed"])
    )
    .collect()[0]
    .asDict()
)
for name, value in null_row.items():
    if name != "row_count":
        measures[name] = value

# COMMAND ----------
# MAGIC %md
# MAGIC ### 3. Enforced Column Masks (GDPR Art. 9 + location)
# MAGIC Special-category biometric columns and precise location are masked at the Unity
# MAGIC Catalog layer: full values for the `fleet_safety_officers` group, redacted/coarsened
# MAGIC for everyone else. The masks are derived from the column classification, so they can
# MAGIC never drift from it, and cover **every** Gold surface carrying the classified data:
# MAGIC the live table, the alerts log, the quarantine side table (DQ-failing rows are still
# MAGIC raw Art. 9 biometrics), and the per-driver aggregates (`avg_heart_rate` / `avg_stress`
# MAGIC — aggregation does not de-identify). A column mask survives a data overwrite, so we
# MAGIC DROP any mask left by a prior run (best-effort) before re-applying — idempotent.

# COMMAND ----------
# 1) (Re)create the mask UDFs once in the Gold schema.
for ddl in mask_function_ddls(function_schema, privileged_group=mask_privileged_group):
    spark.sql(ddl)

# 2) Re-apply masks per table, for whichever masked columns it actually contains.
#    DROP first (ignoring "no mask set" on the first run / unmasked columns), then SET —
#    otherwise SET MASK on an already-masked column from a prior run errors.
#    The quarantine table only exists once a run has quarantined rows (append-created).
mask_targets = [live_status_table, safety_alerts_table, safety_metrics_table]
if spark.catalog.tableExists(live_quarantine_table):
    mask_targets.append(live_quarantine_table)
for table in mask_targets:
    cols = [f.name for f in spark.table(table).schema.fields]
    for ddl in drop_mask_ddls(table, cols):
        try:
            spark.sql(ddl)
        except Exception:
            pass  # column had no mask yet — expected on first run
    for ddl in apply_mask_ddls(
        table, cols, function_schema, privileged_group=mask_privileged_group
    ):
        spark.sql(ddl)
        logger.info(f"Applied mask: {ddl}")

# COMMAND ----------
# MAGIC %md
# MAGIC ### 4. Risk-Score Drift Monitoring
# MAGIC We compare this run's risk-score distribution to a baseline using PSI. Drift is a
# MAGIC **signal, not a failure** (a recalibrated sensor shifts the distribution without any
# MAGIC real safety change), so we log and record it rather than failing the run.

# COMMAND ----------
band_row = (
    spark.sql(band_counts_select_sql(live_status_table, "risk_score"))
    .collect()[0]
    .asDict()
)
current_dist = {k: (v or 0) for k, v in band_row.items()}
report = assess_drift(DEFAULT_BASELINE, current_dist)

measures["risk_score_psi"] = report.psi
for band, count in current_dist.items():
    measures[f"dist_{band}"] = count

if report.is_alerting:
    logger.warning(
        f"⚠️ Risk-score drift {report.severity.upper()} (PSI={report.psi}). Distribution: {current_dist}"
    )
else:
    logger.info(f"Risk-score distribution stable (PSI={report.psi}).")

# COMMAND ----------
# MAGIC %md
# MAGIC ### 5. Flush Pipeline Self-Metrics
# MAGIC One append-only, tall `pipeline_metrics` fact (run_id, stage, metric, value) that a
# MAGIC Grafana panel can trend over time — row counts, quarantine count, join match rate,
# MAGIC drift PSI, and the risk-band distribution.

# COMMAND ----------
rows = metric_rows(run_id, captured_at, "gold", measures)
spark.createDataFrame(rows, METRICS_SCHEMA_DDL).write.mode("append").saveAsTable(
    metrics_fact_table
)
logger.info(f"Wrote {len(rows)} metrics to {metrics_fact_table} for run {run_id}.")

logger.info("✅ Gold Enrichment Complete!")
