"""Exercise GTFS Realtime matching, connection overlays and polling offline."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientSession
from google.transit import gtfs_realtime_pb2 as gtfs

from pyrail.cdn.manifest import ConnectionPage, Manifest, RealtimeFeed
from pyrail.cdn.realtime import RealtimeLoader, apply_realtime
from pyrail.cdn.timetable import Timetable

_DAY = 20261124
_EPOCH = 1795500000
_MINIMUM = datetime.fromtimestamp(_EPOCH, UTC)
_MAXIMUM = datetime.fromtimestamp(_EPOCH + 3600, UTC)
_FEED = RealtimeFeed("https://example.org/realtime.pb", "https://example.org/trips/{trip_id}", None, None)


def _timetable() -> Timetable:
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    page = ConnectionPage("https://example.org/page.arrow", _EPOCH, _MINIMUM, _MAXIMUM)
    return Timetable(
        Manifest("example", ZoneInfo("Europe/Brussels"), _MINIMUM, _MAXIMUM, {}, (page,), (_FEED,), None),
        {
            "stops": {"iri": tuple(f"https://example.org/stops/{number}" for number in range(1, 6))},
            "trips": {"iri": ("https://example.org/trips/IC%3A20270930", "https://example.org/trips/L%3A20270930")},
        },
        (
            (
                page,
                {
                    "iri": ("one", "two", "three", "four", "other"),
                    "tripIdx": (0, 0, 0, 0, 1),
                    "serviceDate": (_DAY,) * 5,
                    "departureStopIdx": (0, 1, 2, 3, 0),
                    "arrivalStopIdx": (1, 2, 3, 4, 1),
                    "stopSequence": (10, 20, 30, 40, 1),
                    "arrivalStopSequence": (20, 30, 40, 50, 2),
                    "departureTimeOffset": (100, 200, 300, 400, 110),
                    "arrivalTimeOffset": (180, 280, 380, 480, 190),
                    "pickupType": (0,) * 5,
                    "dropOffType": (0,) * 5,
                },
            ),
        ),
    )


def _feed() -> Any:
    feed = gtfs.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = _EPOCH
    update = feed.entity.add(id="delayed").trip_update
    update.trip.trip_id = "IC:20271231"
    update.trip.start_date = str(_DAY)
    first = update.stop_time_update.add(stop_sequence=10, stop_id="1_2")
    first.departure.delay = 60
    skipped = update.stop_time_update.add(stop_sequence=30, stop_id="3")
    skipped.schedule_relationship = gtfs.TripUpdate.StopTimeUpdate.SKIPPED
    last = update.stop_time_update.add(stop_id="4_7")
    last.arrival.time = _EPOCH + 390
    last.departure.delay = 20
    canceled = feed.entity.add(id="canceled").trip_update
    canceled.trip.trip_id = "L:20270930"
    canceled.trip.start_date = str(_DAY)
    canceled.trip.schedule_relationship = gtfs.TripDescriptor.CANCELED
    return feed


def test_overlay_keeps_skipped_stops_and_canceled_trips_and_carries_delays() -> None:
    """Apply endpoint updates and propagate delays through unreported stops."""
    timetable = _timetable()
    connections = apply_realtime(timetable, [(_FEED, _feed())])
    assert [row.iri for row in connections] == ["other", "one", "two", "three", "four"]
    canceled, first, second, third, fourth = connections
    assert canceled.canceled
    assert (first.departure_delay, first.arrival_delay, first.departure_platform) == (60, 60, "2")
    assert (second.departure_delay, second.arrival_skipped) == (60, True)
    assert (third.departure_skipped, third.arrival_delay, third.arrival_platform) == (True, 10, "7")
    assert (fourth.departure_delay, fourth.arrival_delay) == (20, 20)
    assert apply_realtime(timetable, [])[0].departure == first.scheduled_departure


def test_no_data_stops_propagation_and_other_service_date_is_ignored() -> None:
    """Reset inherited predictions at NO_DATA and scope cancellation to its date."""
    feed = _feed()
    feed.entity[1].trip_update.trip.start_date = "20261125"
    missing = feed.entity[0].trip_update.stop_time_update[1]
    missing.schedule_relationship = gtfs.TripUpdate.StopTimeUpdate.NO_DATA
    connections = {row.iri: row for row in apply_realtime(_timetable(), [(_FEED, feed)])}
    assert not connections["other"].canceled
    assert connections["three"].departure_delay == 0


def _response(status: int, body: bytes = b"", **headers: str) -> MagicMock:
    result = MagicMock()
    result.__aenter__.return_value = MagicMock(status=status, headers=headers, read=AsyncMock(return_value=body))
    return result


async def test_polling_is_conditional_serialized_and_retains_previous_snapshot() -> None:
    """Concurrent callers share a poll, with 304 and malformed data retaining predictions."""
    session = MagicMock(spec=ClientSession)
    session.get.side_effect = [
        _response(200, _feed().SerializeToString(), ETag='"one"', **{"Last-Modified": "Tue, 24 Nov 2026 00:00:00 GMT"}),
        _response(304),
        _response(200, b"\x80"),
    ]
    loader = RealtimeLoader(session)
    timetable = _timetable()
    with patch("pyrail.cdn.realtime.monotonic", return_value=0) as clock:
        first, concurrent = await asyncio.gather(loader.connections(timetable), loader.connections(timetable))
        assert first == concurrent
        assert session.get.call_count == 1
        clock.return_value = 30
        assert await loader.connections(timetable) == first
        clock.return_value = 60
        assert await loader.connections(timetable) == first
    assert session.get.call_count == 3
    assert session.get.call_args.kwargs["headers"] == {
        "If-None-Match": '"one"',
        "If-Modified-Since": "Tue, 24 Nov 2026 00:00:00 GMT",
    }
