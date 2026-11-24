"""Adapt planned CDN journeys to the existing iRail connection models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import groupby, pairwise
from typing import TYPE_CHECKING

from pyrail.exceptions import NotFoundError
from pyrail.models import (
    ConnectionArrival,
    ConnectionDeparture,
    ConnectionDetails,
    ConnectionsApiResponse,
    ConnectionStop,
    Direction,
    PlatformInfo,
    StationDetails,
    VehicleInfo,
    Via,
)

from .board import lookup_station, trip_vehicles
from .manifest import SCHEMA_VERSION
from .routing import journeys
from .vehicle import build_vehicle_stop

if TYPE_CHECKING:
    from .realtime import Connection
    from .timetable import Timetable


def _leg(
    rows: Sequence[Connection],
    stations: Mapping[int, StationDetails],
    vehicle: VehicleInfo,
    direction: Direction,
    now: datetime,
) -> tuple[ConnectionDeparture, ConnectionArrival]:
    first, last = rows[0], rows[-1]
    origin, destination = stations[first.departure_stop], stations[last.arrival_stop]
    intermediate = []
    for index, (incoming, outgoing) in enumerate(pairwise(rows), start=1):
        stop = build_vehicle_stop(index, stations[outgoing.departure_stop], incoming, outgoing, now)
        intermediate.append(
            ConnectionStop(
                id=stop.id,
                station=stop.station,
                station_info=stop.station_info,
                scheduled_arrival_time=stop.scheduled_arrival_time,
                scheduled_departure_time=stop.scheduled_departure_time,
                arrival_canceled=stop.arrival_canceled,
                departure_canceled=stop.departure_canceled,
                arrived=stop.arrived,
                left=stop.left,
                arrival_delay=stop.arrival_delay,
                departure_delay=stop.departure_delay,
                platform=stop.platform,
                platform_info=stop.platform_info,
            )
        )

    departure = ConnectionDeparture(
        delay=first.departure_delay,
        station=origin.name,
        station_info=origin,
        time=datetime.fromtimestamp(first.scheduled_departure, UTC),
        vehicle=vehicle.name,
        vehicle_info=vehicle,
        canceled=first.canceled,
        departure_connection=first.iri,
        direction=direction,
        left=not first.canceled and first.departure <= now.timestamp(),
        walking=False,
        stops=intermediate,
        platform=first.departure_platform,
        platform_info=None if first.departure_platform is None else PlatformInfo(first.departure_platform),
    )
    arrival = ConnectionArrival(
        delay=last.arrival_delay,
        station=destination.name,
        station_info=destination,
        time=datetime.fromtimestamp(last.scheduled_arrival, UTC),
        vehicle=vehicle.name,
        vehicle_info=vehicle,
        canceled=last.canceled,
        departure_connection=last.iri,
        direction=direction,
        arrived=not last.canceled and last.arrival <= now.timestamp(),
        walking=False,
        platform=last.arrival_platform,
        platform_info=None if last.arrival_platform is None else PlatformInfo(last.arrival_platform),
    )
    return departure, arrival


def _connection(
    path: Sequence[Connection],
    stations: Mapping[int, StationDetails],
    vehicles: Mapping[int, VehicleInfo],
    headsigns: Sequence[str | None],
    now: datetime,
) -> ConnectionDetails:
    legs = []
    for (trip, _), group in groupby(path, key=lambda row: (row.trip_index, row.service_date)):
        rows = list(group)
        direction = Direction(headsigns[trip] or stations[rows[-1].arrival_stop].name)
        legs.append(_leg(rows, stations, vehicles[trip], direction, now))

    vias = [
        Via(
            id=departure.departure_connection,
            arrival=arrival,
            departure=departure,
            timebetween=int((departure.time - arrival.time).total_seconds()) + departure.delay - arrival.delay,
            station=departure.station,
            station_info=departure.station_info,
            vehicle=departure.vehicle,
            vehicle_info=departure.vehicle_info,
        )
        for (_, arrival), (departure, _) in pairwise(legs)
    ]
    return ConnectionDetails(
        id=" ".join(row.iri for row in path),
        departure=legs[0][0],
        arrival=legs[-1][1],
        duration=path[-1].arrival - path[0].departure,
        vias=vias or None,
    )


def build_connections(
    timetable: Timetable,
    rows: Sequence[Connection],
    stations: Mapping[str, StationDetails],
    origin: str,
    destination: str,
    instant: datetime,
    *,
    arrive_by: bool,
    trains_only: bool,
) -> ConnectionsApiResponse:
    """Search one release and return journeys using the public connection models."""
    start = lookup_station(stations, origin)
    end = lookup_station(stations, destination)
    stops = timetable.tables["stops"]
    iris = stops["iri"]
    by_iri = {station.at_id: station for station in stations.values()}
    parents = stops["parentIdx"]
    by_index = {}
    for index, parent in enumerate(parents):
        if (station := by_iri.get(iris[index if parent == -1 else parent])) is not None:
            by_index[index] = station
    now = datetime.now(UTC)
    if start.at_id not in iris or end.at_id not in iris:
        msg = "No timetable stops for the requested stations"
        raise NotFoundError(msg)

    vehicles = trip_vehicles(timetable)
    candidates = [
        row
        for row in rows
        if row.trip_index in vehicles
        and row.departure_stop in by_index
        and row.arrival_stop in by_index
        and (not trains_only or vehicles[row.trip_index].type != "BUS")
    ]
    paths = journeys(
        candidates,
        parents,
        stops["minTransferTime"],
        iris.index(start.at_id),
        iris.index(end.at_id),
        int(instant.timestamp()),
        arrive_by=arrive_by,
    )
    return ConnectionsApiResponse(
        version=SCHEMA_VERSION,
        timestamp=now,
        connections=[
            _connection(path, by_index, vehicles, timetable.tables["trips"]["headsign"], now) for path in paths
        ],
    )
