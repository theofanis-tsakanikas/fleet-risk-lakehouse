"""VED (Vehicle Energy Dataset) parsing and trip normalisation.

VED dynamic CSVs carry one row per OBD/GPS reading with these columns (of ~22, the rest
are powertrain signals this pipeline does not use):

* ``VehId`` / ``Trip`` — vehicle and trip identifiers (a ``VehId``+``Trip`` pair is unique);
* ``DayNum`` — fractional day since the collection period start (encodes the trip's
  absolute start time within its file's week);
* ``Timestamp(ms)`` — milliseconds elapsed since the trip start;
* ``Latitude[deg]`` / ``Longitude[deg]`` / ``Vehicle Speed[km/h]`` — the telemetry, with
  literal ``NaN`` strings where a signal is absent.

Everything here is pure: :func:`parse_ved` takes an iterable of dict rows (as produced by
``csv.DictReader``) so tests can feed literal rows; :func:`load_trips` is the thin file
wrapper. Ordering inside a trip follows ``Timestamp(ms)``, and :func:`resample` reduces a
trip to one point per cadence bucket (last reading wins) for the tracker stream while the
raw trace stays available for event detection.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# The columns this pipeline consumes; a missing header is a malformed input, not a NaN.
REQUIRED_COLUMNS = (
    "VehId",
    "Trip",
    "DayNum",
    "Timestamp(ms)",
    "Latitude[deg]",
    "Longitude[deg]",
    "Vehicle Speed[km/h]",
)


@dataclass(frozen=True)
class TripPoint:
    """One telemetry reading, relative to its trip's start."""

    offset_s: float
    latitude: float | None
    longitude: float | None
    speed_kmh: float | None


@dataclass(frozen=True)
class Trip:
    """One vehicle trip: ordered points plus its start offset within the dataset week."""

    vehicle_id: str
    trip_id: str
    start_offset_s: float  # seconds since the dataset file's week start (from DayNum)
    points: tuple[TripPoint, ...]

    @property
    def duration_s(self) -> float:
        return self.points[-1].offset_s if self.points else 0.0


def _optional_float(raw: str) -> float | None:
    """Parse a VED numeric cell; the literal ``NaN`` (or empty) becomes ``None``."""
    if raw is None or raw == "" or raw.lower() == "nan":
        return None
    return float(raw)


def parse_ved(rows: Iterable[dict[str, str]]) -> list[Trip]:
    """Group VED dict-rows into ordered :class:`Trip` objects.

    Args:
        rows: Dict rows keyed by the VED header names (``csv.DictReader`` output).

    Returns:
        Trips sorted by ``(vehicle_id, start_offset_s)``, each with points sorted by
        ``offset_s``.

    Raises:
        KeyError: If a required VED column is missing from a row (malformed input).
    """
    grouped: dict[tuple[str, str], list[tuple[float, TripPoint, float]]] = {}
    for row in rows:
        key = (row["VehId"], row["Trip"])
        offset_s = float(row["Timestamp(ms)"]) / 1000.0
        # DayNum is 1-based: day 1.5 is noon of the week's first day.
        day_start_s = (float(row["DayNum"]) - 1.0) * 86400.0
        point = TripPoint(
            offset_s=offset_s,
            latitude=_optional_float(row["Latitude[deg]"]),
            longitude=_optional_float(row["Longitude[deg]"]),
            speed_kmh=_optional_float(row["Vehicle Speed[km/h]"]),
        )
        grouped.setdefault(key, []).append((offset_s, point, day_start_s))

    trips = []
    for (veh, trip_id), entries in grouped.items():
        entries.sort(key=lambda e: e[0])
        trips.append(
            Trip(
                vehicle_id=veh,
                trip_id=trip_id,
                # DayNum is constant within a trip; take it from the first reading.
                start_offset_s=entries[0][2],
                points=tuple(p for _, p, _ in entries),
            )
        )
    trips.sort(key=lambda t: (t.vehicle_id, t.start_offset_s))
    return trips


def load_trips(path: str) -> list[Trip]:
    """Read a VED CSV file into trips (see :func:`parse_ved`)."""
    import csv

    with open(path, newline="") as f:
        return parse_ved(csv.DictReader(f))


def resample(trip: Trip, cadence_s: float = 60.0) -> list[TripPoint]:
    """One point per ``cadence_s`` bucket (the bucket's last reading wins).

    The tracker stream replays at fleet-telemetry cadence (default one reading per
    minute, matching the mock producers and the ±60s Gold join window), while event
    detection runs on the raw trace — so downsampling here never hides a braking event.

    Args:
        trip: The trip to resample.
        cadence_s: Bucket width in seconds; must be positive.

    Returns:
        The bucket-last points, ordered, at most one per bucket.
    """
    if cadence_s <= 0:
        raise ValueError(f"cadence_s must be positive, got {cadence_s}")
    by_bucket: dict[int, TripPoint] = {}
    for point in trip.points:
        by_bucket[int(point.offset_s // cadence_s)] = point
    return [by_bucket[b] for b in sorted(by_bucket)]
