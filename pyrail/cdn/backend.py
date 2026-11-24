"""iRail backend that reads the published Linked Connections timetable."""

from __future__ import annotations

from datetime import timedelta
import re
from typing import TYPE_CHECKING, Literal, override

from aiohttp import ClientSession

from pyrail.backend import Backend
from pyrail.exceptions import NotSupportedError
from pyrail.models import (
    ConnectionsApiResponse,
    LiveboardApiResponse,
    StationDetails,
    StationsApiResponse,
    VehicleApiResponse,
)

from .board import build_liveboard, query_time
from .journey import build_connections
from .manifest import MANIFEST_URL, SCHEMA_VERSION
from .timetable import Table, Timetable, TimetableLoader
from .vehicle import build_vehicle, service_day

if TYPE_CHECKING:
    from .realtime import Connection, RealtimeLoader

_STATION_IRI = re.compile(r"https?://irail\.be/stations/NMBS/([0-9]+)")


class CdnBackend(Backend):
    """Serve iRail queries from the CDN using a lazily opened HTTP session."""

    def __init__(
        self,
        lang: str = "en",
        *,
        session: ClientSession | None = None,
        manifest_url: str = MANIFEST_URL,
    ) -> None:
        """Configure the CDN source and optionally use an external session."""
        super().__init__(lang)
        self._session = session
        self._owns_session = session is None
        self._manifest_url = manifest_url
        self._loader: TimetableLoader | None = None
        self._realtime: RealtimeLoader | None = None

    def _timetable_loader(self) -> TimetableLoader:
        if self._session is None:
            self._session = ClientSession()
        if self._session.closed:
            msg = "The CDN session is closed, so no request can be sent"
            raise RuntimeError(msg)
        if self._loader is None:
            self._loader = TimetableLoader(self._session, manifest_url=self._manifest_url)
        return self._loader

    @override
    async def open(self) -> None:
        """Initialize the session and timetable loader."""
        self._timetable_loader()

    @override
    async def close(self) -> None:
        """Release caches and close an owned session."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None
        self._loader = None
        self._realtime = None

    @override
    async def get_stations(self) -> StationsApiResponse:
        """Return journey stations and their names in the selected language."""
        timetable = await self._timetable_loader().load(tables=("stops",), extensions=("stations",))
        stations = _station_details(timetable, self.lang)
        return StationsApiResponse(
            version=SCHEMA_VERSION, timestamp=timetable.manifest.generated_at, stations=list(stations.values())
        )

    @override
    async def get_liveboard(
        self,
        station: str | None = None,
        station_id: str | None = None,
        date: str | None = None,
        time: str | None = None,
        arrdep: Literal["departure", "arrival"] = "departure",
    ) -> LiveboardApiResponse:
        """Build the requested hour of station calls from the scheduled and realtime data."""
        if (station is None) == (station_id is None):
            msg = "Provide exactly one of station or station_id"
            raise ValueError(msg)
        if arrdep not in ("departure", "arrival"):
            msg = "arrdep must be departure or arrival"
            raise ValueError(msg)
        start = query_time(date, time)
        end = start + timedelta(hours=1)
        timetable = await self._timetable_loader().load(
            tables=("stops", "trips"),
            window=(start, end),
            margin=timedelta(hours=8),
            extensions=("stations", "headsigns", "tripEnrichment"),
        )
        rows = await self._connections(timetable)
        stations = _station_details(timetable, self.lang)
        return build_liveboard(
            timetable,
            rows,
            stations,
            station if station is not None else station_id or "",
            self.lang,
            start,
            end,
            arrdep,
        )

    @override
    async def get_connections(
        self,
        from_station: str,
        to_station: str,
        date: str | None = None,
        time: str | None = None,
        timesel: Literal["departure", "arrival"] = "departure",
        type_of_transport: Literal["automatic", "trains", "no_international_trains", "all"] = "automatic",
    ) -> ConnectionsApiResponse:
        """Search the iRail timetable for departures or arrivals near the requested time."""
        if timesel not in ("departure", "arrival"):
            msg = "timesel must be departure or arrival"
            raise ValueError(msg)
        if type_of_transport not in ("automatic", "trains", "no_international_trains", "all"):
            msg = "Invalid type_of_transport"
            raise ValueError(msg)
        if type_of_transport == "no_international_trains":
            msg = "The CDN router does not yet support filtering international trains"
            raise NotSupportedError(msg)
        instant = query_time(date, time)
        arrive_by = timesel == "arrival"
        span = timedelta(hours=6)
        window = (instant - span, instant + timedelta(seconds=1)) if arrive_by else (instant, instant + span)
        timetable = await self._timetable_loader().load(
            tables=("stops", "trips"),
            window=window,
            margin=timedelta(hours=1),
            extensions=("stations", "tripEnrichment"),
        )
        rows = await self._connections(timetable)
        return build_connections(
            timetable,
            rows,
            _station_details(timetable, self.lang),
            from_station,
            to_station,
            instant,
            arrive_by=arrive_by,
            trains_only=type_of_transport != "all",
        )

    @override
    async def get_vehicle(self, vehicle_id: str, date: str | None = None) -> VehicleApiResponse:
        """Build a vehicle response for a Belgian service date."""
        if not vehicle_id:
            msg = "vehicle_id must be provided"
            raise ValueError(msg)
        day, window = service_day(date)
        timetable = await self._timetable_loader().load(
            tables=("stops", "trips"),
            window=window,
            margin=timedelta(hours=12),
            extensions=("stations", "tripEnrichment"),
        )
        rows = await self._connections(timetable)
        return build_vehicle(timetable, rows, _station_details(timetable, self.lang), vehicle_id, day)

    async def _connections(self, timetable: Timetable) -> tuple[Connection, ...]:
        if self._realtime is None:
            try:
                from .realtime import RealtimeLoader  # noqa: PLC0415
            except ImportError as error:
                msg = "Install pyrail[cdn] to use realtime CDN services"
                raise NotSupportedError(msg) from error
            if self._session is None:
                msg = "The CDN session is closed"
                raise RuntimeError(msg)
            self._realtime = RealtimeLoader(self._session)
        return await self._realtime.connections(timetable)

    @override
    async def get_composition(self, vehicle_id: str, date: str | None = None) -> None:
        """Report the absence of public composition data on the CDN."""
        msg = (
            "Train composition needs SNCB's private RIV API. Use the iRail API backend while api.irail.be is available."
        )
        raise NotSupportedError(msg)


def _station_details(timetable: Timetable, lang: str) -> dict[str, StationDetails]:
    stations: dict[str, StationDetails] = {}
    _add_stations(stations, timetable.tables["stops"], "name")
    if (curated := timetable.extensions.get("stations")) is not None:
        _add_stations(stations, curated, f"alternative{lang.title()}")
    return stations


def _add_stations(stations: dict[str, StationDetails], table: Table, name_column: str) -> None:
    parents = table.get("parentIdx", (-1,) * len(table["iri"]))
    for iri, parent, name, translated, lat, lon in zip(
        table["iri"], parents, table["name"], table[name_column], table["lat"], table["lon"], strict=True
    ):
        if parent != -1 or name is None or lat is None or lon is None:
            continue
        match = _STATION_IRI.fullmatch(iri)
        if match is None:
            continue
        station_id = f"BE.NMBS.{match[1]}"
        stations[station_id] = StationDetails(
            at_id=iri, id=station_id, name=translated or name, standard_name=name, latitude=lat, longitude=lon
        )
