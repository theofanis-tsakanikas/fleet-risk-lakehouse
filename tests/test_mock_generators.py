"""Pure-Python tests for the IoT mock generators (no Spark, no cloud).

Covers: emitted-record schema, fleet_config device-mapping fidelity, the
documented anomaly-injection branches (null/sentinel heart rates, negative/glitch
speeds, GPS failures, corrupted IDs, dropped stress score), seed determinism, and
that the anomaly *rates* match the probabilities hard-coded in the producers.
"""

import random
from datetime import datetime, timezone

import generators
import pytest

CONFIG = generators.load_fleet_config(generators.default_config_path())
DRIVER = CONFIG[0]
TS = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


class _SeqRandom:
    """Scripted ``random.random`` returning queued values, then 0.5 forever.

    Note: ``randint``/``choice`` use ``getrandbits`` (not ``random()``), so they do
    not consume the queue. ``uniform`` *does* consume one value, so generator
    branches that call it are avoided by the scripts below (GPS forced to 0,0).
    """

    def __init__(self, values):
        self._values = list(values)

    def __call__(self):
        return self._values.pop(0) if self._values else 0.5


@pytest.fixture
def seq(monkeypatch):
    def _install(values):
        monkeypatch.setattr(generators.random, "random", _SeqRandom(values))

    return _install


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def test_tracker_event_schema():
    event = generators.generate_tracker_event(DRIVER, TS)
    assert set(event) == {
        "tracker_id",
        "truck_id",
        "driver_id",
        "latitude",
        "longitude",
        "speed",
        "fuel_level",
        "status",
        "event_timestamp",
    }
    assert event["event_timestamp"] == TS.isoformat()


def test_watch_event_schema():
    event = generators.generate_watch_event(DRIVER, TS)
    assert set(event) == {"watch_id", "user_id", "event_timestamp", "metrics"}
    assert {"heart_rate", "steps", "battery_level"} <= set(event["metrics"])
    assert event["event_timestamp"] == TS.isoformat()


# --------------------------------------------------------------------------- #
# fleet_config device mappings honored (clean, non-corrupted path)
# --------------------------------------------------------------------------- #
def test_tracker_mappings_honored_when_clean(seq):
    # id_roll>=0.10 (no id corruption), coord 0,0 (skip uniform), speed normal
    seq([0.5, 0.0, 0.5])
    event = generators.generate_tracker_event(DRIVER, TS)
    assert event["tracker_id"] == DRIVER["tracker_id"]
    assert event["truck_id"] == DRIVER["truck_id"]
    assert event["driver_id"] == DRIVER["driver_id"]


def test_watch_mappings_honored_when_clean(seq):
    seq([0.5, 0.5, 0.5])  # id clean, heart normal, stress present
    event = generators.generate_watch_event(DRIVER, TS)
    assert event["watch_id"] == DRIVER["watch_id"]
    assert event["user_id"] == DRIVER["driver_id"]


def test_config_has_ten_unique_drivers():
    assert len(CONFIG) == 10
    assert len({d["driver_id"] for d in CONFIG}) == 10
    assert all({"driver_id", "watch_id", "truck_id", "tracker_id"} <= set(d) for d in CONFIG)


# --------------------------------------------------------------------------- #
# Tracker anomaly branches
# --------------------------------------------------------------------------- #
def test_tracker_truck_id_error_injection(seq):
    seq([0.02, 0.0, 0.5])  # id_roll<0.04
    assert generators.generate_tracker_event(DRIVER, TS)["truck_id"].endswith("_ERR")


def test_tracker_ghost_driver_injection(seq):
    seq([0.05, 0.0, 0.5])  # 0.04<=id_roll<0.07
    assert generators.generate_tracker_event(DRIVER, TS)["driver_id"] == "DRV_999"


def test_tracker_empty_tracker_id_injection(seq):
    seq([0.08, 0.0, 0.5])  # 0.07<=id_roll<0.10
    assert generators.generate_tracker_event(DRIVER, TS)["tracker_id"] == ""


def test_tracker_gps_failure_injection(seq):
    seq([0.5, 0.0, 0.5])  # coord_roll<0.05
    event = generators.generate_tracker_event(DRIVER, TS)
    assert event["latitude"] == 0.0 and event["longitude"] == 0.0


def test_tracker_negative_speed_injection(seq):
    seq([0.5, 0.0, 0.02])  # speed_roll<0.05
    assert generators.generate_tracker_event(DRIVER, TS)["speed"] == -1


def test_tracker_glitch_speed_injection(seq):
    seq([0.5, 0.0, 0.07])  # 0.05<=speed_roll<0.10
    assert generators.generate_tracker_event(DRIVER, TS)["speed"] == 999


# --------------------------------------------------------------------------- #
# Watch anomaly branches
# --------------------------------------------------------------------------- #
def test_watch_null_heart_rate_injection(seq):
    seq([0.5, 0.02, 0.5])  # error_roll<0.05
    assert generators.generate_watch_event(DRIVER, TS)["metrics"]["heart_rate"] is None


def test_watch_sentinel_heart_rate_injection(seq):
    seq([0.5, 0.06, 0.5])  # 0.05<=error_roll<0.08
    assert generators.generate_watch_event(DRIVER, TS)["metrics"]["heart_rate"] == -999


def test_watch_zero_heart_rate_injection(seq):
    seq([0.5, 0.09, 0.5])  # 0.08<=error_roll<0.10
    assert generators.generate_watch_event(DRIVER, TS)["metrics"]["heart_rate"] == 0


def test_watch_outlier_heart_rate_injection(seq):
    seq([0.5, 0.11, 0.5])  # 0.10<=error_roll<0.12
    assert generators.generate_watch_event(DRIVER, TS)["metrics"]["heart_rate"] == 250


def test_watch_incident_heart_rate_injection(seq):
    # 0.12<=error_roll<0.22 -> a genuine extreme heart rate (>110) that survives Silver and
    # trips DANGER: Extreme Heart Rate. seq: id_roll, error_roll, randint, ...stress rolls.
    seq([0.5, 0.15, 0.5])
    hr = generators.generate_watch_event(DRIVER, TS)["metrics"]["heart_rate"]
    assert 111 <= hr <= 155
    assert hr > 110  # above the DANGER threshold (RISK_MODEL.heart_rate_danger)


def test_watch_stress_score_dropped(seq):
    seq([0.5, 0.5, 0.9])  # final roll >= 0.80 -> no stress_score
    assert "stress_score" not in generators.generate_watch_event(DRIVER, TS)["metrics"]


def test_watch_stress_score_present(seq):
    seq([0.5, 0.5, 0.1])  # final roll < 0.80 -> stress_score present
    metrics = generators.generate_watch_event(DRIVER, TS)["metrics"]
    assert 1 <= metrics["stress_score"] <= 100


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def test_tracker_output_deterministic_given_seed():
    random.seed(2026)
    first = [generators.generate_tracker_event(d, TS) for d in CONFIG]
    random.seed(2026)
    second = [generators.generate_tracker_event(d, TS) for d in CONFIG]
    assert first == second


def test_watch_output_deterministic_given_seed():
    random.seed(2026)
    first = [generators.generate_watch_event(d, TS) for d in CONFIG]
    random.seed(2026)
    second = [generators.generate_watch_event(d, TS) for d in CONFIG]
    assert first == second


# --------------------------------------------------------------------------- #
# Anomaly RATES match the producer probabilities (seeded, large sample)
# --------------------------------------------------------------------------- #
N = 40_000


def _rate(predicate, generate):
    random.seed(7)
    hits = sum(1 for _ in range(N) if predicate(generate(DRIVER, TS)))
    return hits / N


@pytest.mark.parametrize(
    "predicate, expected",
    [
        (lambda e: e["truck_id"].endswith("_ERR"), 0.04),
        (lambda e: e["driver_id"] == "DRV_999", 0.03),
        (lambda e: e["tracker_id"] == "", 0.03),
        (lambda e: e["speed"] == -1, 0.05),
        (lambda e: e["speed"] == 999, 0.05),
        (lambda e: e["latitude"] == 0.0 and e["longitude"] == 0.0, 0.05),
    ],
)
def test_tracker_anomaly_rates(predicate, expected):
    assert abs(_rate(predicate, generators.generate_tracker_event) - expected) < 0.01


@pytest.mark.parametrize(
    "predicate, expected",
    [
        (lambda e: e["metrics"]["heart_rate"] is None, 0.05),
        (lambda e: e["metrics"]["heart_rate"] == -999, 0.03),
        (lambda e: e["metrics"]["heart_rate"] == 0, 0.02),
        (lambda e: e["metrics"]["heart_rate"] == 250, 0.02),
        (
            lambda e: 111 <= (e["metrics"]["heart_rate"] or 0) <= 155,
            0.10,
        ),  # genuine DANGER incidents (excl. the 250 sentinel)
        (lambda e: "stress_score" not in e["metrics"], 0.20),
    ],
)
def test_watch_anomaly_rates(predicate, expected):
    assert abs(_rate(predicate, generators.generate_watch_event) - expected) < 0.01
