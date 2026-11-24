"""Compare both iRail backends on the live data they have in common."""

from collections.abc import AsyncIterator, Sequence
import logging
from typing import Literal

from aiohttp import ClientSession
import pytest

from pyrail import CdnBackend, IRail, LiveboardArrival, LiveboardDeparture
from tests.live.live_api import REQUEST_TIMEOUT, LiveApi
from tests.live.test_live_api import BRUSSELS_CENTRAL_ID

logger = logging.getLogger(__name__)


@pytest.fixture
async def cdn() -> AsyncIterator[LiveApi]:
    """Share a CDN snapshot and HTTP session for the duration of each comparison."""
    async with (
        ClientSession(timeout=REQUEST_TIMEOUT) as session,
        IRail(backend=CdnBackend(session=session)) as client,
    ):
        yield LiveApi(client)


async def test_live_station_catalog_parity(live: LiveApi, cdn: LiveApi) -> None:
    """Report release coverage and naming differences by station ID."""
    api = await live.fetch("API stations", lambda rail: rail.get_stations())
    published = await cdn.fetch("CDN stations", lambda rail: rail.get_stations())
    api_names = {station.id: station.name for station in api.stations}
    cdn_names = {station.id: station.name for station in published.stations}
    shared = api_names.keys() & cdn_names.keys()
    assert BRUSSELS_CENTRAL_ID in shared
    logger.info(
        "Stations: %d API, %d CDN, %d shared. Different names (translations or catalog spelling): %s",
        len(api_names),
        len(cdn_names),
        len(shared),
        [(key, api_names[key], cdn_names[key]) for key in sorted(shared) if api_names[key] != cdn_names[key]],
    )
    logger.info(
        "Station IDs listed by just one source (catalog coverage or ID variants): API %s; CDN %s",
        sorted(api_names.keys() - shared),
        sorted(cdn_names.keys() - shared),
    )


async def _board(
    source: LiveApi, date: str, time: str, kind: Literal["arrival", "departure"]
) -> Sequence[LiveboardArrival | LiveboardDeparture]:
    response = await source.fetch(
        f"liveboard ({kind})",
        lambda rail: rail.get_liveboard(station_id=BRUSSELS_CENTRAL_ID, date=date, time=time, arrdep=kind),
    )
    assert response.station_info.id == BRUSSELS_CENTRAL_ID
    entries = response.arrivals if kind == "arrival" else response.departures
    assert entries is not None
    assert len(entries) > 0
    return entries


@pytest.mark.parametrize("kind", ["departure", "arrival"])
async def test_live_board_parity(
    live: LiveApi, cdn: LiveApi, travel_date: tuple[str, str], kind: Literal["arrival", "departure"]
) -> None:
    """Report timetable mismatches and differing predictions on the shared calls."""
    api = await _board(live, *travel_date, kind)
    published = await _board(cdn, *travel_date, kind)
    api_by_call = {(entry.vehicle, entry.time): entry for entry in api}
    cdn_by_call = {(entry.vehicle, entry.time): entry for entry in published}
    shared = api_by_call.keys() & cdn_by_call.keys()
    assert shared
    logger.info(
        "%s board: %d API, %d CDN, %d shared scheduled calls. Calls unique to one source "
        "(schedule, realtime window or coverage): API %s; CDN %s",
        kind,
        len(api),
        len(published),
        len(shared),
        sorted(api_by_call.keys() - shared),
        sorted(cdn_by_call.keys() - shared),
    )
    delay_changes = 0
    platform_changes = 0
    missing_platforms = 0
    cancellation_changes = 0
    for key in shared:
        old, new = api_by_call[key], cdn_by_call[key]
        delay_changes += old.delay != new.delay
        cancellation_changes += old.canceled != new.canceled
        missing_platforms += old.platform is not None and new.platform is None
        platform_changes += old.platform is not None and new.platform is not None and old.platform != new.platform
    logger.info(
        "%s board predictions: %d delay differences, %d cancellation differences, %d shared platforms differ, "
        "%d API platforms missing in CDN TripUpdates.",
        kind,
        delay_changes,
        cancellation_changes,
        platform_changes,
        missing_platforms,
    )


async def test_live_vehicle_parity(live: LiveApi, cdn: LiveApi, travel_date: tuple[str, str]) -> None:
    """Pick a dated run seen in both boards and compare its station sequence and times."""
    api_board = await _board(live, *travel_date, "departure")
    cdn_board = await _board(cdn, *travel_date, "departure")
    candidates = {entry.vehicle for entry in cdn_board if not entry.canceled}
    vehicle = next((entry.vehicle for entry in api_board if not entry.canceled and entry.vehicle in candidates), None)
    assert vehicle is not None
    date, _ = travel_date
    api = await live.fetch("API vehicle", lambda rail: rail.get_vehicle(vehicle, date=date))
    published = await cdn.fetch("CDN vehicle", lambda rail: rail.get_vehicle(vehicle, date=date))
    assert api.vehicle == published.vehicle == vehicle
    api_calls = [(stop.station_info.id, stop.scheduled_departure_time) for stop in api.stops]
    cdn_calls = [(stop.station_info.id, stop.scheduled_departure_time) for stop in published.stops]
    shared = set(api_calls) & set(cdn_calls)
    assert shared
    logger.info(
        "%s: %d API stops, %d CDN stops, %d matching scheduled calls. Same stop order and times: %s. "
        "Calls unique to one source (dated timetable or run selection): API %s; CDN %s",
        vehicle,
        len(api_calls),
        len(cdn_calls),
        len(shared),
        api_calls == cdn_calls,
        [call for call in api_calls if call not in shared],
        [call for call in cdn_calls if call not in shared],
    )

    api_by_call = dict(zip(api_calls, api.stops, strict=True))
    cdn_by_call = dict(zip(cdn_calls, published.stops, strict=True))
    logger.info(
        "%s shared vehicle calls: %d scheduled arrivals differ, %d realtime arrival/departure delays differ, "
        "%d cancellation states differ. Realtime differences can reflect different sources or update times.",
        vehicle,
        sum(api_by_call[key].scheduled_arrival_time != cdn_by_call[key].scheduled_arrival_time for key in shared),
        sum(
            (api_by_call[key].arrival_delay, api_by_call[key].departure_delay)
            != (cdn_by_call[key].arrival_delay, cdn_by_call[key].departure_delay)
            for key in shared
        ),
        sum(api_by_call[key].canceled != cdn_by_call[key].canceled for key in shared),
    )
