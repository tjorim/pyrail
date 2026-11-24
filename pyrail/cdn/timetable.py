"""Load release-consistent timetable data from the iRail CDN."""

from asyncio import Lock
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from http import HTTPStatus
import json
import time
from types import MappingProxyType
from typing import Any
from urllib.request import parse_http_list

from aiohttp import ClientError, ClientSession

from pyrail.exceptions import ApiUnavailableError, InvalidResponseError

from .arrow import ArrowError, read_table
from .manifest import MANIFEST_URL, SCHEMA_VERSION, TABLES, ConnectionPage, Manifest, parse_extensions, parse_manifest
from .schema import COLUMNS, EXTENSION_COLUMNS

type Table = Mapping[str, tuple[Any, ...]]
type Window = tuple[datetime, datetime]
type CacheKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class Timetable:
    """Validated tables and pages pinned to the same release."""

    manifest: Manifest
    tables: Mapping[str, Table]
    pages: tuple[tuple[ConnectionPage, Table], ...]
    extensions: Mapping[str, Table] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(slots=True)
class _Cached[Value]:
    value: Value
    headers: dict[str, str]
    expires_at: float


def _expiry(headers: Mapping[str, str], now: float) -> float | None:
    directives = {}
    for item in parse_http_list(headers.get("cache-control", "")):
        name, _, value = item.partition("=")
        directives[name.strip().lower()] = value.strip().strip('"')
    if "no-store" in directives:
        return None
    if "no-cache" in directives or set(headers.get("vary", "").lower().replace(" ", "").split(",")) - {
        "",
        "accept-encoding",
    }:
        return now
    max_age = directives.get("max-age", "0")
    age = headers.get("age", "0")
    if not (max_age.isascii() and max_age.isdecimal() and age.isascii() and age.isdecimal()):
        return now
    apparent_age = 0.0
    if date := headers.get("date", ""):
        try:
            apparent_age = time.time() - parsedate_to_datetime(date).timestamp()
        except (ValueError, OverflowError, OSError):
            return now
    return now + max(0, int(max_age[:12]) - max(apparent_age, int(age[:12])))


class TimetableLoader:
    """Load requested tables and pages using an externally managed HTTP session.

    The cache is bounded by entry count. Each load works with one manifest, and
    the last successful snapshot stays available if a newer release fails validation.
    """

    def __init__(self, session: ClientSession, *, manifest_url: str = MANIFEST_URL, max_entries: int = 16) -> None:
        """Create an empty in-memory cache."""
        if max_entries <= 0:
            msg = "max_entries must be positive"
            raise ValueError(msg)
        self._session = session
        self._manifest_url = manifest_url
        self._max_entries = max_entries
        self._manifest: OrderedDict[CacheKey, _Cached[Manifest]] = OrderedDict()
        self._catalogs: OrderedDict[CacheKey, _Cached[Mapping[str, str]]] = OrderedDict()
        self._tables: OrderedDict[CacheKey, _Cached[Table]] = OrderedDict()
        self._lock = Lock()
        self._last_usable: Timetable | None = None

    @property
    def last_usable(self) -> Timetable | None:
        """Return the last snapshot whose requested data passed validation."""
        return self._last_usable

    async def load(
        self,
        *,
        tables: Sequence[str] = TABLES,
        window: Window | None = None,
        extensions: Sequence[str] = (),
        margin: timedelta = timedelta(),
    ) -> Timetable:
        """Load the selected core tables and the pages overlapping a departure window.

        Omit the window for table-only calls. A malformed or incompatible response
        raises InvalidResponseError or ArrowError and leaves the last snapshot intact.
        """
        if unknown := set(tables).difference(TABLES):
            msg = f"Unknown timetable tables: {sorted(unknown)}"
            raise ValueError(msg)
        if unknown := set(extensions).difference(EXTENSION_COLUMNS):
            msg = f"Unknown iRail extensions: {sorted(unknown)}"
            raise ValueError(msg)
        async with self._lock:
            manifest = await self._fetch(
                self._manifest,
                ("", "manifest", self._manifest_url),
                _decode_manifest,
                max_entries=1,
            )
            pages = ()
            if window is not None:
                pages = manifest.pages_between(*window)
                if margin > timedelta():
                    start, end = window
                    pages = manifest.pages_between(
                        max(manifest.coverage_start, start - margin), min(manifest.coverage_end, end + margin)
                    )
            catalog = await self._load_catalog(manifest) if extensions else {}
            snapshot = Timetable(
                manifest,
                MappingProxyType(
                    {name: await self._load_table(manifest, name, manifest.tables[name]) for name in tables}
                ),
                tuple([(page, await self._load_table(manifest, "connections", page.url)) for page in pages]),
                MappingProxyType(
                    {
                        name: await self._load_table(manifest, name, catalog[name])
                        for name in extensions
                        if name in catalog
                    }
                ),
            )
            self._last_usable = snapshot
            return snapshot

    async def _load_catalog(self, manifest: Manifest) -> Mapping[str, str]:
        if manifest.extensions_url is None:
            return dict[str, str]()

        def decode(data: bytes, response_url: str) -> Mapping[str, str]:
            return parse_extensions(_decode_json(data, response_url), response_url, manifest.release_id)

        return await self._fetch(
            self._catalogs, (manifest.release_id, "extensions", manifest.extensions_url), decode, max_entries=1
        )

    async def _load_table(self, manifest: Manifest, name: str, url: str) -> Table:
        version, columns = (
            ("1-alpha", EXTENSION_COLUMNS[name]) if name in EXTENSION_COLUMNS else (SCHEMA_VERSION, COLUMNS[name])
        )

        def decode(data: bytes, response_url: str) -> Table:
            try:
                values = read_table(
                    data,
                    expected_metadata={
                        "schemaVersion": version,
                        "releaseId": manifest.release_id,
                        "dataset": name,
                    },
                    expected_columns=columns,
                )
            except ArrowError as error:
                msg = f"Incompatible {name} table from {response_url}: {error}"
                raise ArrowError(msg) from error
            return MappingProxyType({column: tuple(rows) for column, rows in values.items()})

        return await self._fetch(self._tables, (manifest.release_id, name, url), decode, max_entries=self._max_entries)

    async def _fetch[Value](
        self,
        cache: OrderedDict[CacheKey, _Cached[Value]],
        key: CacheKey,
        decode: Callable[[bytes, str], Value],
        *,
        max_entries: int,
    ) -> Value:
        cached = cache.get(key)
        headers = {}
        if cached is not None:
            if time.monotonic() < cached.expires_at:
                cache.move_to_end(key)
                return cached.value
            if (etag := cached.headers.get("etag")) is not None:
                headers["If-None-Match"] = etag
            if (modified := cached.headers.get("last-modified")) is not None:
                headers["If-Modified-Since"] = modified
        url = key[2]
        try:
            async with self._session.get(url, headers=headers) as response:
                response_headers = {name.lower(): value for name, value in response.headers.items()}
                if response.status == HTTPStatus.NOT_MODIFIED and cached is not None and headers:
                    value = cached.value
                    response_headers = {
                        name: value for name, value in cached.headers.items() if name not in {"age", "date"}
                    } | response_headers
                elif response.status == HTTPStatus.OK:
                    value = decode(await response.read(), str(response.url))
                else:
                    msg = f"iRail CDN returned HTTP {response.status} for {url}"
                    raise InvalidResponseError(msg, status=response.status)
        except (ClientError, TimeoutError) as error:
            msg = f"Could not load iRail CDN resource {url}: {error}"
            raise ApiUnavailableError(msg) from error
        expires_at = _expiry(response_headers, time.monotonic())
        if expires_at is None:
            cache.pop(key, None)
        else:
            cache[key] = _Cached(value, response_headers, expires_at)
            cache.move_to_end(key)
            if len(cache) > max_entries:
                cache.popitem(last=False)
        return value


def _decode_json(data: bytes, response_url: str) -> Any:
    try:
        return json.loads(data)
    except (ValueError, UnicodeError) as error:
        msg = f"Malformed iRail CDN JSON from {response_url}"
        raise InvalidResponseError(msg) from error


def _decode_manifest(data: bytes, response_url: str) -> Manifest:
    return parse_manifest(_decode_json(data, response_url), response_url)
