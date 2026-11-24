"""Offline checks for release discovery, Arrow validation and HTTP caching."""

from datetime import UTC, datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from aiohttp import ClientSession
import pyarrow as pa
import pytest

from pyrail.cdn.arrow import ArrowError
from pyrail.cdn.manifest import parse_manifest
from pyrail.cdn.schema import COLUMNS
from pyrail.cdn.timetable import TimetableLoader
from pyrail.exceptions import InvalidResponseError

_MANIFEST_URL = "https://example.org/releases/current.json"
_RESPONSE_URL = "https://files.example.org/cdn/manifest.jsonld"
_WINDOW = (datetime(2026, 11, 24, 8, tzinfo=UTC), datetime(2026, 11, 24, 9, tzinfo=UTC))


def _manifest(release: str, *, version: str = "2-alpha") -> dict[str, Any]:
    return {
        "schemaVersion": version,
        "releaseId": release,
        "timeZone": "Europe/Brussels",
        "coverageStart": "2026-11-24T00:00:00Z",
        "coverageEnd": "2026-11-25T00:00:00Z",
        **{name: f"{release}/{name}.arrow" for name in ("stops", "routes", "trips", "transfers")},
        "connections": {
            "pages": [
                {
                    "@id": f"{release}/page1.arrow",
                    "epochSeconds": 1795500000,
                    "minDepartureTime": "2026-11-24T06:00:00Z",
                    "maxDepartureTime": "2026-11-24T08:00:00Z",
                },
                {
                    "@id": f"{release}/page2.arrow",
                    "epochSeconds": 1795500000,
                    "minDepartureTime": "2026-11-24T09:00:00Z",
                    "maxDepartureTime": "2026-11-24T12:00:00Z",
                },
            ],
        },
        "realtime": [
            {"@id": "/live/updates.pb", "tripTemplate": "https://example.org/trips/{trip_id}"},
        ],
        "irail:extensions": {"@id": f"{release}/irail.json"},
    }


def _file(
    name: str,
    release: str,
    *,
    version: str = "2-alpha",
    column_overrides: dict[str, pa.DataType] | None = None,
) -> bytes:
    kinds = {"i": pa.int32(), "I": pa.uint32(), "B": pa.uint8(), "utf8": pa.string(), "d": pa.float64()}
    types = {key: kinds[kind] for key, kind in COLUMNS[name].items()} | (column_overrides or {})
    schema = pa.schema(
        list(types.items()),
        metadata={"schemaVersion": version, "releaseId": release, "dataset": name},
    )
    with pa.BufferOutputStream() as output:
        with pa.ipc.new_file(output, schema) as writer:
            writer.write_table(
                pa.Table.from_arrays([pa.array([], type=kind) for kind in types.values()], schema=schema)
            )
        return bytes(output.getvalue())


def _response(
    body: bytes = b"", *, status: int = 200, url: str = _RESPONSE_URL, headers: dict[str, str] | None = None
) -> MagicMock:
    response = MagicMock(status=status, url=url, headers=headers or {})
    response.read = AsyncMock(return_value=body)
    context = MagicMock()
    context.__aenter__.return_value = response
    return context


def test_manifest_resolves_links_and_selects_pages_by_departure_bounds() -> None:
    """Use links resolved at the final URL and include departures at the lower bound."""
    manifest = parse_manifest(_manifest("next"), _RESPONSE_URL)
    assert manifest.timezone.key == "Europe/Brussels"
    assert manifest.tables["stops"] == "https://files.example.org/cdn/next/stops.arrow"
    assert manifest.extensions_url == "https://files.example.org/cdn/next/irail.json"
    assert manifest.realtime[0].url == "https://files.example.org/live/updates.pb"
    assert [page.url for page in manifest.pages_between(*_WINDOW)] == ["https://files.example.org/cdn/next/page1.arrow"]
    with pytest.raises(ValueError, match="within the release coverage"):
        manifest.pages_between(datetime(2026, 11, 23, tzinfo=UTC), _WINDOW[1])


async def test_only_requested_resources_load_and_respect_http_freshness() -> None:
    """Skip unused resources and avoid HTTP requests while cached objects are fresh."""
    session = MagicMock(spec=ClientSession)
    session.get.side_effect = [
        _response(json.dumps(_manifest("one")).encode(), headers={"Cache-Control": "max-age=60"}),
        _response(_file("stops", "one"), headers={"Cache-Control": "max-age=60"}),
        _response(_file("connections", "one"), headers={"Cache-Control": "max-age=60"}),
    ]
    loader = TimetableLoader(session, manifest_url=_MANIFEST_URL)
    first = await loader.load(tables=("stops",), window=_WINDOW)
    second = await loader.load(tables=("stops",), window=_WINDOW)
    assert first == second
    assert first.tables["stops"]["name"] == ()
    assert first.pages[0][1]["tripIdx"] == ()
    assert [call.args[0] for call in session.get.call_args_list] == [
        _MANIFEST_URL,
        "https://files.example.org/cdn/one/stops.arrow",
        "https://files.example.org/cdn/one/page1.arrow",
    ]


async def test_conditional_requests_and_release_switch() -> None:
    """Use validators and keep snapshots already returned to callers pinned."""
    session = MagicMock(spec=ClientSession)
    session.get.side_effect = [
        _response(json.dumps(_manifest("one")).encode(), headers={"Last-Modified": "Wed, 25 Nov 2026 00:00:00 GMT"}),
        _response(_file("stops", "one"), headers={"ETag": '"stops-one"'}),
        _response(status=304),
        _response(status=304),
        _response(json.dumps(_manifest("two")).encode()),
        _response(_file("stops", "two")),
    ]
    loader = TimetableLoader(session, manifest_url=_MANIFEST_URL, max_entries=1)
    first = await loader.load(tables=("stops",))
    revalidated = await loader.load(tables=("stops",))
    second = await loader.load(tables=("stops",))
    assert first == revalidated
    assert session.get.call_args_list[2].kwargs["headers"] == {"If-Modified-Since": "Wed, 25 Nov 2026 00:00:00 GMT"}
    assert session.get.call_args_list[3].kwargs["headers"] == {"If-None-Match": '"stops-one"'}
    assert session.get.call_args_list[5].kwargs["headers"] == {}
    assert loader.last_usable is second
    assert first.manifest.release_id == "one"
    assert second.manifest.release_id == "two"


@pytest.mark.parametrize(
    ("release", "version", "column_overrides", "message"),
    [
        ("one", "2-alpha", None, "releaseId"),
        ("two", "3", None, "schemaVersion"),
        ("two", "2-alpha", {"lat": pa.int32()}, "column 'lat'"),
    ],
)
async def test_incompatible_arrow_preserves_last_snapshot(
    release: str,
    version: str,
    column_overrides: dict[str, pa.DataType] | None,
    message: str,
) -> None:
    """Detect bad versions, release IDs and column types before committing a snapshot."""
    session = MagicMock(spec=ClientSession)
    session.get.side_effect = [
        _response(json.dumps(_manifest("one")).encode()),
        _response(_file("stops", "one")),
        _response(json.dumps(_manifest("two")).encode()),
        _response(_file("stops", release, version=version, column_overrides=column_overrides)),
    ]
    loader = TimetableLoader(session, manifest_url=_MANIFEST_URL)
    first = await loader.load(tables=("stops",))
    with pytest.raises(ArrowError, match=message):
        await loader.load(tables=("stops",))
    assert loader.last_usable is first


def test_unsupported_manifest_version() -> None:
    """Reject manifest versions whose schemas the reader does not implement."""
    with pytest.raises(InvalidResponseError, match="Unsupported Linked Connections schemaVersion"):
        parse_manifest(_manifest("future", version="3"), _RESPONSE_URL)
