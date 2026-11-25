"""Construct iRail liveboard models from dated connection rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
import re
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from pyrail.exceptions import NotFoundError
from pyrail.models import (
    LiveboardApiResponse,
    LiveboardArrival,
    LiveboardDeparture,
    PlatformInfo,
    StationDetails,
    VehicleInfo,
)

from .manifest import SCHEMA_VERSION

if TYPE_CHECKING:
    from .realtime import Connection
    from .timetable import Timetable

_BELGIUM = ZoneInfo("Europe/Brussels")
_VEHICLE = re.compile(r"([A-Za-z]+)([0-9]+)")


def query_time(date: str | None, time: str | None) -> datetime:
    """Resolve the existing date and time parameters to an unambiguous UTC instant."""
    now = datetime.now(_BELGIUM)
    if date is None and time is None:
        return now.astimezone(UTC)
    date = now.strftime("%d%m%y") if date is None else date
    time = now.strftime("%H%M") if time is None else time
    if re.fullmatch(r"[0-9]{6}", date) is None or re.fullmatch(r"[0-9]{4}", time) is None:
        msg = "Expected date DDMMYY and time HHMM"
        raise ValueError(msg)
    local = datetime.strptime(date + time, "%d%m%y%H%M").replace(tzinfo=_BELGIUM)
    utc = local.astimezone(UTC)
    if utc.astimezone(_BELGIUM) != local:
        msg = "The requested time does not exist in Belgian local time"
        raise ValueError(msg)
    return utc


def lookup_station(stations: Mapping[str, StationDetails], query: str) -> StationDetails:
    """Find a station by its ID, IRI or name."""
    key = query.strip().casefold()
    matches = [
        station
        for station in stations.values()
        if key
        in {station.id.casefold(), station.at_id.casefold(), station.name.casefold(), station.standard_name.casefold()}
    ]
    if len(matches) != 1:
        msg = f"Unknown or ambiguous station: {query}"
        raise NotFoundError(msg)
    return matches[0]


def trip_vehicles(timetable: Timetable) -> dict[int, VehicleInfo]:
    """Map published trip identities to the iRail vehicle identifier and short name."""
    table = timetable.extensions.get("tripEnrichment")
    if table is None:
        return {}
    result: dict[int, VehicleInfo] = {}
    for index, iri in zip(table["tripIdx"], table["vehicleIri"], strict=True):
        if not iri:
            continue
        code = iri.rsplit("/", 1)[-1]
        match = _VEHICLE.fullmatch(code)
        if match is None:
            continue
        kind, number = match.groups()
        if kind == "S" and len(number) > 4:  # noqa: PLR2004
            kind += number[:-4]
            number = number[-4:]
        result[index] = VehicleInfo(
            name=f"BE.NMBS.{code}",
            short_name=f"{kind} {number}",
            number=number,
            type=kind,
            at_id=iri,
        )
    return result


def _headsigns(timetable: Timetable, lang: str) -> dict[str, str]:
    table = timetable.extensions.get("headsigns")
    column = f"translation{lang.title()}"
    if table is None or column not in table:
        return {}
    return {
        headsign: translation
        for headsign, translation in zip(table["headsign"], table[column], strict=True)
        if translation
    }


def _run_ends(rows: Sequence[Connection]) -> dict[tuple[int, int], tuple[Connection, Connection]]:
    ends: dict[tuple[int, int], tuple[Connection, Connection]] = {}
    for row in rows:
        key = (row.trip_index, row.service_date)
        first, last = ends.get(key, (row, row))
        if row.departure_sequence < first.departure_sequence:
            first = row
        if row.arrival_sequence > last.arrival_sequence:
            last = row
        ends[key] = (first, last)
    return ends


def build_liveboard(
    timetable: Timetable,
    rows: Sequence[Connection],
    stations: Mapping[str, StationDetails],
    query: str,
    lang: str,
    start: datetime,
    end: datetime,
    kind: Literal["departure", "arrival"],
) -> LiveboardApiResponse:
    """Show station calls from one release, including skipped or canceled calls."""
    station = lookup_station(stations, query)
    by_iri = {stop.at_id: stop for stop in stations.values()}
    stop_iris = timetable.tables["stops"]["iri"]
    parents = timetable.tables["stops"]["parentIdx"]
    station_indices = {index for index, iri in enumerate(stop_iris) if iri == station.at_id}
    stop_ids = station_indices | {index for index, parent in enumerate(parents) if parent in station_indices}
    vehicles = trip_vehicles(timetable)
    ends = _run_ends(rows)
    headsigns = _headsigns(timetable, lang)
    arrivals: list[LiveboardArrival] = []
    departures: list[LiveboardDeparture] = []
    is_arrival = kind == "arrival"
    now = datetime.now(UTC)
    clock = now.timestamp()
    window_start, window_end = start.timestamp(), end.timestamp()
    for row in rows:
        stop = row.arrival_stop if is_arrival else row.departure_stop
        effective = row.arrival if is_arrival else row.departure
        skipped = row.arrival_skipped if is_arrival else row.departure_skipped
        rule = row.drop_off_type if is_arrival else row.pickup_type
        if stop not in stop_ids or not window_start <= effective <= window_end or (rule == 1 and not skipped):
            continue
        vehicle = vehicles.get(row.trip_index)
        first, last = ends[row.trip_index, row.service_date]
        endpoint = first.departure_stop if is_arrival else last.arrival_stop
        parent = parents[endpoint]
        other = by_iri.get(stop_iris[parent if parent >= 0 else endpoint])
        if other is None or vehicle is None:
            continue
        if not is_arrival:
            raw = timetable.tables["trips"]["headsign"][row.trip_index]
            if raw is not None:
                other = replace(other, name=headsigns.get(raw, other.name))
        platform = row.arrival_platform if is_arrival else row.departure_platform
        platform_info = PlatformInfo(platform) if platform is not None else None
        canceled = row.canceled or skipped
        if is_arrival:
            arrivals.append(
                LiveboardArrival(
                    id=row.iri,
                    departure_connection=row.iri,
                    station=other.name,
                    station_info=other,
                    time=datetime.fromtimestamp(row.scheduled_arrival, UTC),
                    delay=row.arrival_delay,
                    canceled=canceled,
                    arrived=not canceled and effective <= clock,
                    vehicle=vehicle.name,
                    vehicle_info=vehicle,
                    platform=platform,
                    platform_info=platform_info,
                )
            )
        else:
            departures.append(
                LiveboardDeparture(
                    id=row.iri,
                    departure_connection=row.iri,
                    station=other.name,
                    station_info=other,
                    time=datetime.fromtimestamp(row.scheduled_departure, UTC),
                    delay=row.departure_delay,
                    canceled=canceled,
                    left=not canceled and effective <= clock,
                    vehicle=vehicle.name,
                    vehicle_info=vehicle,
                    platform=platform,
                    platform_info=platform_info,
                )
            )
    return LiveboardApiResponse(
        version=SCHEMA_VERSION,
        timestamp=now,
        station=station.name,
        station_info=station,
        arrivals=sorted(arrivals, key=lambda entry: entry.time) if is_arrival else None,
        departures=None if is_arrival else sorted(departures, key=lambda entry: entry.time),
    )
