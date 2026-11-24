"""Discovery and time-window selection for the iRail Linked Connections release."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pyrail.exceptions import InvalidResponseError

MANIFEST_URL = "https://irail.github.io/iRail-cdn/manifest.jsonld"
SCHEMA_VERSION = "2-alpha"
TABLES = ("stops", "routes", "trips", "transfers")


@dataclass(frozen=True, slots=True)
class ConnectionPage:
    """An immutable connection page and its inclusive departure bounds."""

    url: str
    minimum: datetime
    maximum: datetime


@dataclass(frozen=True, slots=True)
class RealtimeFeed:
    """The realtime snapshot URL and templates for resolving GTFS IDs."""

    url: str
    trip_template: str
    stop_template: str | None
    route_template: str | None


@dataclass(frozen=True, slots=True)
class Manifest:
    """Links belonging to one scheduled timetable release."""

    release_id: str
    timezone: ZoneInfo
    coverage_start: datetime
    coverage_end: datetime
    tables: Mapping[str, str]
    pages: tuple[ConnectionPage, ...]
    realtime: tuple[RealtimeFeed, ...]
    extensions_url: str | None

    def pages_between(self, start: datetime, end: datetime) -> tuple[ConnectionPage, ...]:
        """Return pages overlapping the half-open departure window [start, end)."""
        if start.utcoffset() is None or end.utcoffset() is None:
            msg = "The timetable window must use timezone-aware datetimes"
            raise ValueError(msg)
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        if not self.coverage_start <= start < end <= self.coverage_end:
            msg = "The timetable window must be nonempty and within the release coverage"
            raise ValueError(msg)
        return tuple(page for page in self.pages if page.maximum >= start and page.minimum < end)


def _text(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value:
        msg = f"{key} must be a nonempty string"
        raise ValueError(msg)
    return value


def _url(value: Any, base_url: str) -> str:
    if isinstance(value, dict):
        value = value.get("@id")
    url = urljoin(base_url, _text(value, "link"))
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        msg = f"Unsupported CDN link {url!r}"
        raise ValueError(msg)
    return url


def _instant(data: dict[str, Any], key: str) -> datetime:
    value = datetime.fromisoformat(_text(data[key], key))
    if value.utcoffset() is None:
        msg = f"{key} must include a timezone"
        raise ValueError(msg)
    return value.astimezone(UTC)


def _optional_template(feed: dict[str, Any], key: str) -> str | None:
    return _text(feed[key], key) if key in feed else None


def parse_manifest(data: Any, base_url: str) -> Manifest:
    """Validate the iRail CDN manifest and resolve links against the fetched URL."""
    try:
        if data["schemaVersion"] != SCHEMA_VERSION:
            msg = f"Unsupported Linked Connections schemaVersion {data['schemaVersion']!r}"
            raise InvalidResponseError(msg)
        start = _instant(data, "coverageStart")
        end = _instant(data, "coverageEnd")
        pages = tuple(
            ConnectionPage(_url(page, base_url), _instant(page, "minDepartureTime"), _instant(page, "maxDepartureTime"))
            for page in data["connections"]["pages"]
        )
        if start >= end or any(not start <= page.minimum <= page.maximum < end for page in pages):
            msg = "Invalid timetable coverage or connection page bounds"
            raise InvalidResponseError(msg)
        extensions = data.get("irail:extensions")
        return Manifest(
            release_id=_text(data["releaseId"], "releaseId"),
            timezone=ZoneInfo(_text(data["timeZone"], "timeZone")),
            coverage_start=start,
            coverage_end=end,
            tables=MappingProxyType({table: _url(data[table], base_url) for table in TABLES}),
            pages=tuple(sorted(pages, key=lambda page: page.minimum)),
            realtime=tuple(
                RealtimeFeed(
                    _url(feed, base_url),
                    _text(feed["tripTemplate"], "tripTemplate"),
                    _optional_template(feed, "stopTemplate"),
                    _optional_template(feed, "routeTemplate"),
                )
                for feed in data.get("realtime", ())
            ),
            extensions_url=None if extensions is None else _url(extensions, base_url),
        )
    except (AttributeError, KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as error:
        msg = f"Invalid iRail CDN manifest from {base_url}: {error}"
        raise InvalidResponseError(msg) from error
