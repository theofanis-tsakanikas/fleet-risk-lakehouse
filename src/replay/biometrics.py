"""Driver biometrics conditioned on real driving events.

No public dataset pairs a driver's wearable stream with their vehicle's telemetry, so the
replay biometric stream is **simulated — but conditioned on the real driving events**
detected in the VED trace, and documented as such (honesty beats fabricated realism):

* a **hard-braking event** (decel > :data:`HARSH_BRAKE_DECEL_KMH_S` between consecutive raw
  readings) triggers an acute heart-rate/stress response that decays exponentially
  (:data:`RESPONSE_DECAY_S`);
* driving above the fleet's overspeed threshold (from
  :data:`fleet_transforms.risk_model.RISK_MODEL` — the same single source of truth the
  risk score and alerts use) sustains an elevated baseline while it lasts.

The model is deterministic: the same trip, seed and ticks always produce the same stream
(no wall-clock, no shared RNG state), so tests can assert exact behaviour. Outputs stay
inside the Silver validity ranges (heart rate 1–220), so real replays exercise the Gold
logic rather than the reject rules — the mock generators already cover dirty data.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from fleet_transforms.risk_model import RISK_MODEL

from replay.ved import TripPoint

# A speed drop steeper than this (km/h per second) between consecutive raw readings is a
# hard-braking event. 8 km/h/s ≈ 2.2 m/s² — the usual telematics harsh-braking threshold.
HARSH_BRAKE_DECEL_KMH_S = 8.0

# Acute stress response half-life-ish decay constant: exp(-Δt / 90s).
RESPONSE_DECAY_S = 90.0

# Ignore raw-reading gaps larger than this when computing deceleration (GPS dropouts).
_MAX_SAMPLE_GAP_S = 3.0

# Acute response magnitudes and physiological clamps.
_HR_EVENT_GAIN = 40
_HR_OVERSPEED_GAIN = 12
_HR_RANGE = (45, 185)
_STRESS_EVENT_GAIN = 55
_STRESS_OVERSPEED_GAIN = 20
_STRESS_RANGE = (1, 100)


@dataclass(frozen=True)
class BiometricPoint:
    """One wearable reading, relative to the trip start."""

    offset_s: float
    heart_rate: int
    stress_score: int


def detect_harsh_brakes(points: tuple[TripPoint, ...] | list[TripPoint]) -> list[float]:
    """Offsets (seconds) of hard-braking events in a raw trip trace.

    Args:
        points: The trip's raw (un-resampled) points, ordered by ``offset_s``.

    Returns:
        The ``offset_s`` of each reading where deceleration since the previous reading
        exceeded :data:`HARSH_BRAKE_DECEL_KMH_S`, skipping gaps > 3 s (sensor dropouts).
    """
    events = []
    prev: TripPoint | None = None
    for point in points:
        if prev is not None and prev.speed_kmh is not None and point.speed_kmh is not None:
            dt = point.offset_s - prev.offset_s
            if 0 < dt <= _MAX_SAMPLE_GAP_S:
                decel = (prev.speed_kmh - point.speed_kmh) / dt
                if decel > HARSH_BRAKE_DECEL_KMH_S:
                    events.append(point.offset_s)
        prev = point
    return events


def _acute_response(offset_s: float, events: list[float]) -> float:
    """Summed, capped exponential response to all events at or before ``offset_s``."""
    response = 0.0
    for event_offset in events:
        if event_offset <= offset_s:
            response += math.exp(-(offset_s - event_offset) / RESPONSE_DECAY_S)
    return min(response, 1.5)


def biometric_series(
    ticks: list[TripPoint],
    events: list[float],
    seed: int,
) -> list[BiometricPoint]:
    """The wearable stream for one trip, one reading per tick.

    Args:
        ticks: The resampled (cadence) points — their ``offset_s`` set the reading times
            and their ``speed_kmh`` drives the overspeed condition.
        events: Hard-braking offsets from :func:`detect_harsh_brakes` (raw trace).
        seed: Per-driver/trip seed; same inputs → identical stream.

    Returns:
        One :class:`BiometricPoint` per tick, clamped to physiological (and
        Silver-validity) ranges.
    """
    rng = random.Random(seed)
    baseline_hr = 66 + rng.randint(0, 10)
    baseline_stress = 15 + rng.randint(0, 15)

    series = []
    for tick in ticks:
        response = _acute_response(tick.offset_s, events)
        overspeed = 1.0 if (tick.speed_kmh or 0.0) > RISK_MODEL.overspeed else 0.0
        jitter = rng.randint(-3, 3)

        heart_rate = round(baseline_hr + _HR_EVENT_GAIN * response + _HR_OVERSPEED_GAIN * overspeed + jitter)
        stress = round(baseline_stress + _STRESS_EVENT_GAIN * response + _STRESS_OVERSPEED_GAIN * overspeed + jitter)

        series.append(
            BiometricPoint(
                offset_s=tick.offset_s,
                heart_rate=max(_HR_RANGE[0], min(_HR_RANGE[1], heart_rate)),
                stress_score=max(_STRESS_RANGE[0], min(_STRESS_RANGE[1], stress)),
            )
        )
    return series
