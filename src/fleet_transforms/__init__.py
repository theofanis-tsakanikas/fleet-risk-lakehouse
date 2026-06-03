"""Pure, importable Spark transforms for the Fleet Monitoring medallion pipeline.

The Bronze/Silver/Gold notebooks keep only the thin, environment-bound layer
(Auto Loader, streaming reads/writes, Unity Catalog, ``DatabricksSession``).
The transformation *logic* lives here as functions that take their
``SparkSession``/``DataFrame`` inputs as parameters and rely on no Databricks
globals (``spark``/``dbutils``), so it can be exercised locally with a plain
``pyspark`` session and zero cloud infrastructure.
"""
