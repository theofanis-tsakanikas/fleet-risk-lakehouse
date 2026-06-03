"""Silver-layer cleansing transforms (pure DataFrame -> DataFrame).

Each function takes a Bronze DataFrame and returns the sanitized Silver
DataFrame. The logic is identical to what previously lived inline in the
``silver_trackers.py`` / ``silver_watches.py`` notebooks; the notebooks now call
these functions, passing the streaming Bronze DataFrame, while the
``readStream``/``writeStream`` plumbing stays in the notebook layer.

The chains work the same on batch or streaming DataFrames, so tests feed a small
batch DataFrame built locally.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, IntegerType, TimestampType


def transform_trackers_silver(df_bronze: DataFrame) -> DataFrame:
    """Apply the Trackers Silver cleansing rules.

    Casts types; prunes malformed truck IDs (``_ERR``), missing tracker IDs and
    the ghost driver ``DRV_999``; nulls out GPS failures ``(0, 0)`` and the speed
    sentinels ``-1``/``999``; trims+uppercases ``status``; and deduplicates on
    ``(tracker_id, event_timestamp)``.

    Args:
        df_bronze: Raw Trackers Bronze DataFrame (or stream).

    Returns:
        The cleaned Silver DataFrame with processing metadata and final columns.
    """
    return (
        df_bronze
        # 1. Cast columns to proper types
        .withColumn("latitude", F.col("latitude").cast(DoubleType()))
        .withColumn("longitude", F.col("longitude").cast(DoubleType()))
        .withColumn("speed", F.col("speed").cast(IntegerType()))
        .withColumn("fuel_level", F.col("fuel_level").cast(IntegerType()))
        .withColumn("event_timestamp", F.col("event_timestamp").cast(TimestampType()))
        # Rule 1: Filter out Malformed Truck IDs and Missing Tracker IDs
        .filter(
            (~F.col("truck_id").contains("_ERR"))
            & (F.col("tracker_id") != "")
            & (F.col("tracker_id").isNotNull())
            & (F.col("driver_id") != "DRV_999")  # Ensuring only valid drivers move to Silver
        )
        # Rule 2: Handle GPS Failures (0.0, 0.0) -> NULL to avoid plotting errors
        .withColumn(
            "latitude",
            F.when(F.col("latitude") == 0, F.lit(None)).otherwise(F.col("latitude")),
        )
        .withColumn(
            "longitude",
            F.when(F.col("longitude") == 0, F.lit(None)).otherwise(F.col("longitude")),
        )
        # Rule 3: Handle Speed Outliers (-1 sensor error, 999 glitch) -> NULL
        .withColumn(
            "speed",
            F.when(F.col("speed").isin([-1, 999]), F.lit(None)).otherwise(F.col("speed")),
        )
        # Rule 4: Standardize Status Strings (trim + uppercase)
        .withColumn("status", F.upper(F.trim(F.col("status"))))
        # Rule 5: Deduplication
        .dropDuplicates(["tracker_id", "event_timestamp"])
        # 2. Add Silver Processing Metadata
        .withColumn("processed_timestamp", F.current_timestamp())
        # 3. Final Column Selection
        .select(
            "tracker_id",
            "truck_id",
            "driver_id",
            "latitude",
            "longitude",
            "speed",
            "fuel_level",
            "status",
            "event_timestamp",
            "ingestion_timestamp",
            "processed_timestamp",
            "source_file",
        )
    )


def transform_watches_silver(df_bronze: DataFrame) -> DataFrame:
    """Apply the Watches Silver cleansing rules.

    Flattens the nested ``metrics`` struct and casts types; prunes malformed watch
    IDs (``_ERR``), missing watch IDs and the ghost driver ``DRV_999``; nulls out
    invalid heart rates (``-999``, ``0`` and impossible ``> 220``); and
    deduplicates on ``(watch_id, event_timestamp)``.

    Args:
        df_bronze: Raw Watches Bronze DataFrame (or stream) with nested ``metrics``.

    Returns:
        The cleaned, flattened Silver DataFrame with processing metadata.
    """
    return (
        df_bronze
        # 1. Flatten nested metrics and cast to proper types
        .withColumn("heart_rate", F.col("metrics.heart_rate").cast(IntegerType()))
        .withColumn("steps", F.col("metrics.steps").cast(IntegerType()))
        .withColumn("battery_level", F.col("metrics.battery_level").cast(IntegerType()))
        .withColumn("stress_score", F.col("metrics.stress_score").cast(IntegerType()))
        # 2. Convert event_timestamp from ISO string to Timestamp
        .withColumn("event_timestamp", F.col("event_timestamp").cast(TimestampType()))
        # Rule 1: Filter out Malformed IDs ('_ERR') or Missing IDs and unknown drivers
        .filter(
            (~F.col("watch_id").contains("_ERR"))
            & (F.col("watch_id") != "")
            & (F.col("watch_id").isNotNull())
            & (F.col("user_id") != "DRV_999")  # Drop unknown drivers to keep Silver clean
        )
        # Rule 2: Handle Invalid Sensor Data (Heart Rate)
        # -999 hardware error / 0 dead sensor / > 220 impossible outlier -> NULL
        .withColumn(
            "heart_rate",
            F.when(F.col("heart_rate").isin([-999, 0]), F.lit(None))
            .when(F.col("heart_rate") > 220, F.lit(None))
            .otherwise(F.col("heart_rate")),
        )
        # Rule 3: Deduplication (handle the 20% duplicate injection from producer)
        .dropDuplicates(["watch_id", "event_timestamp"])
        # 3. Add Silver Processing Metadata
        .withColumn("processed_timestamp", F.current_timestamp())
        # 4. Final Column Selection
        .select(
            "watch_id",
            "user_id",
            "event_timestamp",
            "heart_rate",
            "steps",
            "battery_level",
            "stress_score",
            "ingestion_timestamp",
            "processed_timestamp",
            "source_file",
        )
    )
