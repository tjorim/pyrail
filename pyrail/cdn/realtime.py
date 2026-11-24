"""Poll and apply GTFS Realtime trip updates to an immutable timetable snapshot."""

from __future__ import annotations

from asyncio import Lock
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from http import HTTPStatus
import logging
from time import monotonic
from typing import Any
from urllib.parse import quote, unquote

from aiohttp import ClientError, ClientSession
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2 as gtfs

from pyrail.exceptions import InvalidResponseError

from .manifest import RealtimeFeed
from .timetable import Timetable

logger = logging.getLogger(__name__)
_SERVICE_DATE_LENGTH = 8


@dataclass(slots=True)
class _Feed:
    next_poll: float = 0
    etag: str | None = None
    last_modified: str | None = None
    snapshot: Any = None


class RealtimeLoader:
    """Refresh advertised feeds at most once per interval, retaining the last valid copy."""

    def __init__(self, session: ClientSession, *, poll_interval: float = 30) -> None:
        """Use an externally owned HTTP session, refreshing when callers request data."""
        if poll_interval <= 0:
            msg = "poll_interval must be positive"
            raise ValueError(msg)
        self._session = session
        self._poll_interval = poll_interval
        self._lock = Lock()
        self._feeds: dict[str, _Feed] = {}

    async def connections(self, timetable: Timetable) -> tuple[Connection, ...]:
        """Return scheduled connections with applicable realtime updates."""
        async with self._lock:
            fetch = [(source, await self._refresh(source.url)) for source in timetable.manifest.realtime]
        return apply_realtime(timetable, fetch)

    async def _refresh(self, url: str) -> Any:
        cache = self._feeds.setdefault(url, _Feed())
        if monotonic() < cache.next_poll:
            return cache.snapshot
        headers = {}
        if cache.etag is not None:
            headers["If-None-Match"] = cache.etag
        if cache.last_modified is not None:
            headers["If-Modified-Since"] = cache.last_modified
        try:
            async with self._session.get(url, headers=headers) as response:
                if response.status == HTTPStatus.NOT_MODIFIED and cache.snapshot is not None:
                    return cache.snapshot
                response.raise_for_status()
                snapshot = _decode(await response.read(), cache.snapshot)
                cache.snapshot = snapshot
                cache.etag = response.headers.get("ETag")
                cache.last_modified = response.headers.get("Last-Modified")
        except (ClientError, TimeoutError, DecodeError, InvalidResponseError) as error:
            logger.warning("Could not refresh iRail TripUpdates from %s: %s", url, error)
        finally:
            cache.next_poll = monotonic() + self._poll_interval
        return cache.snapshot


def _decode(data: bytes, previous: Any) -> Any:
    snapshot = gtfs.FeedMessage.FromString(data)
    if not snapshot.IsInitialized() or snapshot.header.incrementality != gtfs.FeedHeader.FULL_DATASET:
        msg = "Expected a complete GTFS Realtime snapshot"
        raise InvalidResponseError(msg)
    if (
        previous is not None
        and snapshot.header.HasField("timestamp")
        and snapshot.header.timestamp < previous.header.timestamp
    ):
        msg = "TripUpdates timestamp moved backwards"
        raise InvalidResponseError(msg)
    return snapshot


@dataclass(frozen=True, slots=True)
class Connection:
    """A scheduled connection with separate realtime information and effective times."""

    iri: str
    trip_index: int
    service_date: int
    departure_stop: int
    arrival_stop: int
    departure_sequence: int
    arrival_sequence: int
    scheduled_departure: int
    scheduled_arrival: int
    pickup_type: int
    drop_off_type: int
    departure_delay: int = 0
    arrival_delay: int = 0
    departure_platform: str | None = None
    arrival_platform: str | None = None
    canceled: bool = False
    departure_skipped: bool = False
    arrival_skipped: bool = False

    @property
    def departure(self) -> int:
        """Estimated departure as Unix seconds."""
        return self.scheduled_departure + self.departure_delay

    @property
    def arrival(self) -> int:
        """Estimated arrival as Unix seconds."""
        return self.scheduled_arrival + self.arrival_delay


def _scheduled(timetable: Timetable) -> dict[tuple[int, int], list[Connection]]:
    by_run: dict[tuple[int, int], list[Connection]] = defaultdict(list)
    for page, table in timetable.pages:
        for iri, trip, day, origin, target, dep_seq, arr_seq, dep, arr, pickup, drop_off in zip(
            table["iri"],
            table["tripIdx"],
            table["serviceDate"],
            table["departureStopIdx"],
            table["arrivalStopIdx"],
            table["stopSequence"],
            table["arrivalStopSequence"],
            table["departureTimeOffset"],
            table["arrivalTimeOffset"],
            table["pickupType"],
            table["dropOffType"],
            strict=True,
        ):
            by_run[trip, day].append(
                Connection(
                    iri,
                    trip,
                    day,
                    origin,
                    target,
                    dep_seq,
                    arr_seq,
                    page.epoch_seconds + dep,
                    page.epoch_seconds + arr,
                    pickup,
                    drop_off,
                )
            )
    return by_run


def _date_key(raw: str) -> int | None:
    if len(raw) != _SERVICE_DATE_LENGTH or not raw.isascii() or not raw.isdecimal():
        return None
    try:
        return int(date.fromisoformat(raw).strftime("%Y%m%d"))
    except ValueError:
        return None


def _dated_updates(feed: Any) -> Iterator[tuple[Any, int]]:
    for entity in feed.entity:
        if entity.is_deleted or not entity.HasField("trip_update"):
            continue
        update = entity.trip_update
        trip = update.trip
        day = _date_key(trip.start_date)
        if day is not None and trip.schedule_relationship in {
            gtfs.TripDescriptor.SCHEDULED,
            gtfs.TripDescriptor.CANCELED,
            gtfs.TripDescriptor.DELETED,
        }:
            yield update, day


def _matching_updates(
    timetable: Timetable,
    feeds: Sequence[tuple[RealtimeFeed, Any]],
    runs: Mapping[tuple[int, int], list[Connection]],
) -> dict[tuple[int, int], Any]:
    trip_iris = timetable.tables["trips"]["iri"]
    direct = {iri: idx for idx, iri in enumerate(trip_iris)}
    matched: dict[tuple[int, int], Any] = {}
    for source, feed in feeds:
        if feed is None:
            continue
        prefix, token, suffix = source.trip_template.partition("{trip_id}")
        if not token:
            continue
        aliases: dict[str, list[int]] = defaultdict(list)
        for idx, iri in enumerate(trip_iris):
            if iri.startswith(prefix) and iri.endswith(suffix):
                raw = unquote(iri[len(prefix) : len(iri) - len(suffix)])
                aliases[raw.rpartition(":")[0]].append(idx)
        for update, day in _dated_updates(feed):
            trip_id = update.trip.trip_id
            index = direct.get(f"{prefix}{quote(trip_id, safe='')}{suffix}")
            if index is None and (alias := trip_id.rpartition(":")[0]) and len(aliases[alias]) == 1:
                index = aliases[alias][0]
            if index is None or (index, day) not in runs:
                continue
            old = matched.get((index, day))
            if old is None or update.timestamp >= old.timestamp:
                matched[index, day] = update
    return matched


def _stop_number(value: str) -> str:
    return value.rsplit("/", 1)[-1].partition("_")[0].lstrip("0")


def _event_delay(event: Any, scheduled: int | None) -> int | None:
    if event.HasField("time") and scheduled is not None:
        return int(event.time - scheduled)
    if event.HasField("delay"):
        return int(event.delay)
    return None


@dataclass(frozen=True, slots=True)
class _StopUpdate:
    arrival: int | None
    departure: int | None
    platform: str | None
    skipped: bool
    no_data: bool


def _stop_updates(rows: Sequence[Connection], station_iris: Sequence[str], trip: Any) -> dict[int, _StopUpdate]:
    arrivals = {row.arrival_sequence: row.scheduled_arrival for row in rows}
    departures = {row.departure_sequence: row.scheduled_departure for row in rows}
    sequences: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        sequences[_stop_number(station_iris[row.departure_stop])].add(row.departure_sequence)
        sequences[_stop_number(station_iris[row.arrival_stop])].add(row.arrival_sequence)
    stops = {}
    for update in trip.stop_time_update:
        if update.HasField("stop_sequence"):
            sequence = int(update.stop_sequence)
        else:
            matches = sequences[_stop_number(update.stop_id)]
            if len(matches) != 1:
                continue
            sequence = next(iter(matches))
        _, _, platform = update.stop_id.partition("_")
        stops[sequence] = _StopUpdate(
            _event_delay(update.arrival, arrivals.get(sequence)),
            _event_delay(update.departure, departures.get(sequence)),
            platform or None,
            update.schedule_relationship == gtfs.TripUpdate.StopTimeUpdate.SKIPPED,
            update.schedule_relationship == gtfs.TripUpdate.StopTimeUpdate.NO_DATA,
        )
    return stops


def _overlay(rows: Sequence[Connection], stations: Sequence[str], update: Any) -> list[Connection]:
    if update.trip.schedule_relationship in {gtfs.TripDescriptor.CANCELED, gtfs.TripDescriptor.DELETED}:
        return [replace(row, canceled=True) for row in rows]
    stops = _stop_updates(rows, stations, update)
    sequences = []
    delays = []
    for sequence, stop in sorted(stops.items()):
        delay = stop.departure if stop.departure is not None else stop.arrival
        if stop.no_data or (not stop.skipped and delay is not None):
            sequences.append(sequence)
            delays.append(0 if stop.no_data else delay)

    def delay_at(sequence: int, *, departure: bool) -> int:
        stop = stops.get(sequence)
        if stop is not None and not stop.skipped and not stop.no_data:
            own = stop.departure if departure else stop.arrival
            other = stop.arrival if departure else stop.departure
            if own is not None:
                return own
            if other is not None:
                return other
        idx = bisect_right(sequences, sequence) - 1
        return (delays[idx] or 0) if idx >= 0 else int(update.delay)

    result = []
    for row in rows:
        origin = stops.get(row.departure_sequence)
        target = stops.get(row.arrival_sequence)
        departure_delay = max(0, delay_at(row.departure_sequence, departure=True))
        arrival_delay = max(
            row.scheduled_departure + departure_delay - row.scheduled_arrival,
            delay_at(row.arrival_sequence, departure=False),
        )
        result.append(
            replace(
                row,
                departure_delay=departure_delay,
                arrival_delay=arrival_delay,
                departure_platform=None if origin is None else origin.platform,
                arrival_platform=None if target is None else target.platform,
                departure_skipped=origin is not None and origin.skipped,
                arrival_skipped=target is not None and target.skipped,
            )
        )
    return result


def apply_realtime(timetable: Timetable, feeds: Sequence[tuple[RealtimeFeed, Any]]) -> tuple[Connection, ...]:
    """Apply a batch of decoded feeds, keeping scheduled data intact and sorting by effective departure.

    The timetable must include the stops and trips tables. Date-scoped matching
    applies updates to the same service date. Fallback IDs must resolve uniquely
    across the entire trips table because the supplied pages may cover only part of a day.
    """
    runs = _scheduled(timetable)
    updates = _matching_updates(timetable, feeds, runs)
    stations = timetable.tables["stops"]["iri"]
    rows: list[Connection] = []
    for key, connections in runs.items():
        if key in updates:
            rows.extend(_overlay(connections, stations, updates[key]))
        else:
            rows.extend(connections)
    return tuple(sorted(rows, key=lambda row: (row.departure, row.iri)))
