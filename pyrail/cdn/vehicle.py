"""Build a dated vehicle response from the connections for one scheduled run."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pyrail.exceptions import InvalidResponseError, NotFoundError
from pyrail.models import PlatformInfo, StationDetails, VehicleApiResponse, VehicleStop

from .board import query_time, trip_vehicles
from .manifest import SCHEMA_VERSION

if TYPE_CHECKING:
    from .realtime import Connection
    from .timetable import Timetable, Window


def service_day(date: str | None) -> tuple[int, Window]:
    """Return the date key and two consecutive Belgian midnights in UTC."""
    start = query_time(date, "0000").astimezone(ZoneInfo("Europe/Brussels"))
    return int(start.strftime("%Y%m%d")), (start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC))


def _stop(
    index: int,
    station: StationDetails,
    incoming: Connection | None,
    outgoing: Connection | None,
    now: datetime,
) -> VehicleStop:
    if incoming is None:
        assert outgoing is not None  # noqa: S101
        arriving, arrival_delay, arrival_canceled = outgoing.scheduled_departure, 0, outgoing.canceled
    else:
        arriving, arrival_delay = incoming.scheduled_arrival, incoming.arrival_delay
        arrival_canceled = incoming.canceled or incoming.arrival_skipped
    if outgoing is None:
        departing, departure_delay, departure_canceled = arriving, 0, arrival_canceled
    else:
        departing, departure_delay = outgoing.scheduled_departure, outgoing.departure_delay
        departure_canceled = outgoing.canceled or outgoing.departure_skipped

    platform = outgoing.departure_platform if outgoing is not None else None
    if platform is None and incoming is not None:
        platform = incoming.arrival_platform
    arrival = datetime.fromtimestamp(arriving, UTC)
    departure = datetime.fromtimestamp(departing, UTC)
    return VehicleStop(
        id=str(index),
        station=station.name,
        station_info=station,
        time=arrival if outgoing is None else departure,
        scheduled_departure_time=departure,
        scheduled_arrival_time=arrival,
        delay=arrival_delay if outgoing is None else departure_delay,
        canceled=arrival_canceled or departure_canceled,
        departure_delay=departure_delay,
        departure_canceled=departure_canceled,
        arrival_delay=arrival_delay,
        arrival_canceled=arrival_canceled,
        left=outgoing is not None and not departure_canceled and outgoing.departure <= now.timestamp(),
        arrived=incoming is not None and not arrival_canceled and incoming.arrival <= now.timestamp(),
        platform=platform,
        platform_info=None if platform is None else PlatformInfo(name=platform),
        departure_connection=None if outgoing is None else outgoing.iri,
    )


def build_vehicle(
    timetable: Timetable,
    rows: Sequence[Connection],
    stations: Mapping[str, StationDetails],
    vehicle_id: str,
    day: int,
) -> VehicleApiResponse:
    """Find the first dated run of the vehicle and reconstruct its ordered calls."""
    code = vehicle_id.strip().upper().removeprefix("BE.NMBS.")
    vehicles = trip_vehicles(timetable)
    candidates = {index for index, vehicle in vehicles.items() if vehicle.name.removeprefix("BE.NMBS.") == code}
    runs: dict[int, list[Connection]] = defaultdict(list)
    for row in rows:
        if row.service_date == day and row.trip_index in candidates:
            runs[row.trip_index].append(row)
    if not runs:
        msg = f"Vehicle {vehicle_id} not found on {day}"
        raise NotFoundError(msg)
    trip = min(runs, key=lambda index: (min(row.scheduled_departure for row in runs[index]), index))
    run = sorted(runs[trip], key=lambda row: row.departure_sequence)
    stop_iris = timetable.tables["stops"]["iri"]
    by_iri = {station.at_id: station for station in stations.values()}
    now = datetime.now(UTC)
    stops = []
    for index, (incoming, outgoing) in enumerate(pairwise([None, *run, None])):
        if outgoing is not None:
            stop = outgoing.departure_stop
        else:
            assert incoming is not None  # noqa: S101
            stop = incoming.arrival_stop
        station = by_iri.get(stop_iris[stop])
        if station is None:
            msg = f"Missing station details for {stop_iris[stop]}"
            raise InvalidResponseError(msg)
        stops.append(_stop(index, station, incoming, outgoing, now))
    vehicle = replace(
        vehicles[trip], latitude=stops[0].station_info.latitude, longitude=stops[0].station_info.longitude
    )
    return VehicleApiResponse(
        version=SCHEMA_VERSION, timestamp=now, vehicle=vehicle.name, vehicle_info=vehicle, stops=stops
    )
