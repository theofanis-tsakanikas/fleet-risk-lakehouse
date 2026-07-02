"""Replay real-world trips through the fleet pipeline.

The mock generators (``src/mock_generator``) exercise the cleansing rules with synthetic
noise; this package feeds the *same* Bronze contract with **real vehicle telemetry** from
the Vehicle Energy Dataset (VED — see ``data/ved/README.md``), so the temporal join, risk
scoring, drift monitoring and masking downstream operate on trips that actually happened.

Three pure modules plus one entry point:

* :mod:`replay.ved` — parse VED CSVs into normalised, ordered trips.
* :mod:`replay.biometrics` — deterministic driver biometrics *conditioned on the real
  driving events* (hard braking, overspeed) detected in each trip.
* :mod:`replay.replay` — map vehicles onto the pseudonymised fleet, rebase trip time onto
  a replay anchor, and emit tracker/watch events in exactly the mock generators' schemas.
* :mod:`replay.producer_replay` — the CLI/job entry point that writes the batch files.
"""
