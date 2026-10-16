"""Live smoke tests: call every iRail endpoint and check the models still deserialize.

These guard against upstream API changes that recorded fixtures cannot detect. They only
assert stable structure, never specific trains, times, counts or disturbances. Detailed
field assertions and error handling are covered by the offline suite in test_irail.py.
"""

from collections.abc import Awaitable, Callable
from typing import Literal

from pyrail.irail import iRail
from pyrail.models import (
    CompositionApiResponse,
    ConnectionsApiResponse,
    DisturbancesApiResponse,
    LiveboardApiResponse,
    StationsApiResponse,
    VehicleApiResponse,
)
from tests.live.live_api import LiveApi

BRUSSELS_CENTRAL_ID = "BE.NMBS.008813003"


async def _first_vehicle_id(live: LiveApi, travel_date: tuple[str, str]) -> str:
    """Pick a vehicle that is valid right now from a busy station's liveboard.

    The vehicle and composition endpoints need a real vehicle id, and ids go stale with
    the timetable, so it is looked up dynamically instead of hardcoded.
    """
    date, time = travel_date
    liveboard = await live.fetch(
        "liveboard", lambda api: api.get_liveboard(id=BRUSSELS_CENTRAL_ID, date=date, time=time)
    )
    departures = [d for d in liveboard.departures or [] if not d.canceled]
    assert departures, "Expected Brussels-Central to have departures to pick a vehicle from"
    return departures[0].vehicle


async def test_live_stations(live: LiveApi) -> None:
    """The stations endpoint returns a non-empty list of stations."""
    response = await live.fetch("stations", lambda api: api.get_stations())

    assert isinstance(response, StationsApiResponse)
    assert response.stations
    assert all(station.id.startswith("BE.NMBS.") and station.name for station in response.stations)


async def test_live_liveboard(live: LiveApi, travel_date: tuple[str, str]) -> None:
    """The liveboard endpoint returns departures and arrivals for a station."""
    date, time = travel_date
    departures = await live.fetch(
        "liveboard (departure)", lambda api: api.get_liveboard(station="Brussels-Central", date=date, time=time)
    )
    arrivals = await live.fetch(
        "liveboard (arrival)",
        lambda api: api.get_liveboard(station="Brussels-Central", date=date, time=time, arrdep="arrival"),
    )

    assert isinstance(departures, LiveboardApiResponse)
    assert departures.station_info.id == BRUSSELS_CENTRAL_ID
    assert departures.departures is not None
    assert len(departures.departures) > 0
    assert all(d.vehicle and d.vehicle_info.name for d in departures.departures)

    assert isinstance(arrivals, LiveboardApiResponse)
    assert arrivals.arrivals is not None
    assert len(arrivals.arrivals) > 0
    assert all(a.vehicle and a.vehicle_info.name for a in arrivals.arrivals)


async def test_live_liveboard_by_id_with_alerts(live: LiveApi, travel_date: tuple[str, str]) -> None:
    """A liveboard requested by station id, with and without alerts, deserializes for both board types."""
    date, time = travel_date
    for arrdep in ("departure", "arrival"):
        for alerts in (False, True):
            response = await live.fetch(
                f"liveboard (id, {arrdep}, alerts={alerts})",
                lambda api, arrdep=arrdep, alerts=alerts: api.get_liveboard(
                    id=BRUSSELS_CENTRAL_ID, date=date, time=time, arrdep=arrdep, alerts=alerts
                ),
            )

            assert isinstance(response, LiveboardApiResponse)
            assert response.station_info.id == BRUSSELS_CENTRAL_ID
            board = response.arrivals if arrdep == "arrival" else response.departures
            assert board is not None
            assert len(board) > 0


async def test_live_connections(live: LiveApi, travel_date: tuple[str, str]) -> None:
    """The connections endpoint returns routes between two stations."""
    date, time = travel_date
    response = await live.fetch(
        "connections",
        lambda api: api.get_connections("Antwerpen-Centraal", "Brussel-Centraal", date=date, time=time),
    )

    assert isinstance(response, ConnectionsApiResponse)
    assert response.connections
    assert all(c.departure.vehicle and c.arrival.station_info.id for c in response.connections)


async def test_live_connections_timesel_and_type_of_transport(live: LiveApi, travel_date: tuple[str, str]) -> None:
    """Connections deserialize when selected by arrival time and for each transport filter."""
    date, time = travel_date
    variants: dict[str, Callable[[iRail], Awaitable[ConnectionsApiResponse | None]]] = {
        "timesel=arrival": lambda api: api.get_connections(
            "Antwerpen-Centraal", "Brussel-Centraal", date=date, time=time, timesel="arrival"
        ),
        "typeOfTransport=trains": lambda api: api.get_connections(
            "Antwerpen-Centraal", "Brussel-Centraal", date=date, time=time, type_of_transport="trains"
        ),
        "typeOfTransport=no_international_trains": lambda api: api.get_connections(
            "Antwerpen-Centraal", "Brussel-Centraal", date=date, time=time, type_of_transport="no_international_trains"
        ),
        "typeOfTransport=all": lambda api: api.get_connections(
            "Antwerpen-Centraal", "Brussel-Centraal", date=date, time=time, type_of_transport="all"
        ),
    }
    for label, request in variants.items():
        response = await live.fetch(f"connections ({label})", request)

        assert isinstance(response, ConnectionsApiResponse)
        assert response.connections, label


async def test_live_no_international_trains_filter(live: LiveApi, travel_date: tuple[str, str]) -> None:
    """The no-international-trains filter changes the result.

    The API silently treats an unrecognised typeOfTransport as 'automatic', so merely deserializing
    would not notice a misspelt value. Brussels-South to Paris-North is served by international trains
    only when they are not filtered out.
    """
    date, time = travel_date

    async def vehicle_types(type_of_transport: Literal["automatic", "no_international_trains"]) -> set[str]:
        response = await live.fetch(
            f"connections (typeOfTransport={type_of_transport})",
            lambda api: api.get_connections(
                "Brussel-Zuid", "Paris-Nord", date=date, time=time, type_of_transport=type_of_transport
            ),
        )
        return {c.departure.vehicle_info.type for c in response.connections}

    automatic = await vehicle_types("automatic")
    filtered = await vehicle_types("no_international_trains")

    assert automatic
    assert filtered
    assert filtered != automatic


async def test_live_vehicle(live: LiveApi, travel_date: tuple[str, str]) -> None:
    """The vehicle endpoint returns the stops of a vehicle taken from a liveboard."""
    date, _ = travel_date
    vehicle_id = await _first_vehicle_id(live, travel_date)

    response = await live.fetch("vehicle", lambda api: api.get_vehicle(vehicle_id, date=date))

    assert isinstance(response, VehicleApiResponse)
    assert response.vehicle == vehicle_id
    assert response.stops
    assert all(stop.station_info.id for stop in response.stops)


async def test_live_composition(live: LiveApi, travel_date: tuple[str, str]) -> None:
    """The composition endpoint returns the segments of a vehicle taken from a liveboard."""
    vehicle_id = await _first_vehicle_id(live, travel_date)

    response = await live.fetch("composition", lambda api: api.get_composition(vehicle_id))

    assert isinstance(response, CompositionApiResponse)
    assert response.composition
    assert all(segment.origin.id and segment.destination.id for segment in response.composition)


async def test_live_disturbances(live: LiveApi) -> None:
    """The disturbances endpoint deserializes, whether or not any disturbance is active."""
    response = await live.fetch("disturbances", lambda api: api.get_disturbances())

    assert isinstance(response, DisturbancesApiResponse)
    assert isinstance(response.disturbances, list)
