"""iRail backend that reads the published Linked Connections timetable."""

import re
from typing import override

from aiohttp import ClientSession

from pyrail.backend import Backend
from pyrail.exceptions import NotSupportedError
from pyrail.models import StationDetails, StationsApiResponse

from .manifest import MANIFEST_URL, SCHEMA_VERSION
from .timetable import Table, TimetableLoader

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

    @override
    async def get_stations(self) -> StationsApiResponse:
        """Return journey stations and their names in the selected language."""
        timetable = await self._timetable_loader().load(tables=("stops",), extensions=("stations",))
        stations = {}
        _add_stations(stations, timetable.tables["stops"], "name")
        if (curated := timetable.extensions.get("stations")) is not None:
            _add_stations(stations, curated, f"alternative{self.lang.title()}")
        return StationsApiResponse(
            version=SCHEMA_VERSION, timestamp=timetable.manifest.generated_at, stations=list(stations.values())
        )

    @override
    async def get_composition(self, vehicle_id: str, date: str | None = None) -> None:
        """Report the absence of public composition data on the CDN."""
        msg = (
            "Train composition needs SNCB's private RIV API. Use the iRail API backend while api.irail.be is available."
        )
        raise NotSupportedError(msg)


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
