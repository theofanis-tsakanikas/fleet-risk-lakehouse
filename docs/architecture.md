# Architecture

The diagrams below are the source of truth for the system shape; keep them in sync with the
code (they are plain Mermaid, so they render on GitHub and diff in PRs — unlike the banner
image in the README).

## End-to-end data flow (Medallion)

```mermaid
flowchart LR
    subgraph gen["Mock IoT generators"]
        GT["producer_trackers\nCSV"]
        GW["producer_watches\nJSON"]
    end

    subgraph lake["AWS S3 + UC Volumes (landing zone)"]
        LT["trackers/"]
        LW["watches/"]
    end

    subgraph bronze["Bronze — Auto Loader (cloudFiles)"]
        BT["trackers_raw"]
        BW["watches_raw"]
    end

    subgraph silver["Silver — cleanse + dedup"]
        ST["trackers_clean"]
        SW["watches_clean"]
    end

    subgraph gold["Gold — enrich + risk + govern"]
        EV["fleet_enriched_view\n(±60s temporal join + risk_score)"]
        LS["fleet_live_status"]
        DM["driver_safety_metrics"]
        AL["fleet_safety_alerts"]
        DD["dim_driver (SCD2)"]
        PM["pipeline_metrics"]
        QT["*_quarantine"]
    end

    BI["Grafana / Streamlit\n(serverless SQL Warehouse)"]

    GT --> LT --> BT --> ST --> EV
    GW --> LW --> BW --> SW --> EV
    ST --> DD
    EV --> LS
    EV --> DM
    EV --> AL
    LS -.quarantined rows.-> QT
    EV -.run metrics + drift PSI.-> PM
    LS --> BI
    DM --> BI
    AL --> BI
    DD --> BI
```

## Gold layer: quality, governance & observability gates

What happens inside the `gold_fleet_enrichment` task, beyond the joins:

```mermaid
flowchart TD
    EV["fleet_enriched_view"] --> NE{"empty?"}
    NE -- "yes" --> FAIL["raise — fail the run\n(timestamp skew / empty Silver)"]
    NE -- "no" --> DQ["evaluate live_status\nexpectation suite (from RISK_MODEL)"]
    DQ --> SPLIT{"split valid / quarantine"}
    SPLIT -- "valid rows" --> WRITE["write fleet_live_status"]
    SPLIT -- "ERROR violations" --> Q["append *_quarantine\n(+ _dq_failures)"]
    DQ --> ENF{"any ERROR breached?"}
    ENF -- "yes" --> FAIL
    ENF -- "no" --> WRITE
    WRITE --> MASK["apply UC column masks\n(biometrics NULL / location coarsened\nexcept fleet_safety_officers)"]
    WRITE --> DRIFT["risk-score PSI vs baseline\n(WARN only — signal, not failure)"]
    MASK --> PM["pipeline_metrics (tall fact)"]
    DRIFT --> PM
```

## Infrastructure layers (Terraform)

```mermaid
flowchart TD
    L1["01_infra\nS3 · IAM · Secrets Manager · SPN\nMetastore · Workspace"]
    L2["02_workspace\nSQL Warehouse · metastore grants"]
    L3["03_unity_catalog\nstorage creds · external locations\ncatalogs · schemas · volumes"]
    DABS["databricks.yml (DABs)\n2 jobs × 8 tasks: mock + real-data replay"]

    L1 -- "remote_state: workspace_url,\nmetastore_id, role_arn, secrets_id" --> L2
    L1 -- "remote_state" --> L3
    L2 --> DABS
    L3 --> DABS
```

See the [ADRs](adr/) for the rationale behind each major decision (layered state, temporal
join window, SQL-warehouse BI, micro-batch execution, declarative DQ, SCD2 dimension, column
masking, real-data replay).
