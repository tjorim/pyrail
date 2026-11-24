"""Tests for forward and arrive-by connection scans."""

from dataclasses import replace

from pyrail.cdn.realtime import Connection
from pyrail.cdn.routing import journeys


def _edge(
    name: str, trip: int, origin: int, destination: int, departure: int, arrival: int, sequence: int = 1
) -> Connection:
    return Connection(name, trip, 20261124, origin, destination, sequence, sequence + 1, departure, arrival, 0, 0)


def test_scans_ignore_impossible_transfers_and_find_later_alternatives() -> None:
    """Respect station buffers and keep distinct later departures."""
    rows = [
        _edge("feeder", 0, 0, 1, 10, 20),
        _edge("too soon", 1, 1, 2, 22, 30),
        _edge("valid transfer", 2, 1, 2, 25, 35),
        _edge("direct", 3, 0, 2, 30, 40),
    ]
    parents, change = (-1,) * 3, (0, 5, 0)
    assert [[row.iri for row in path] for path in journeys(rows, parents, change, 0, 2, 10)] == [
        ["feeder", "valid transfer"],
        ["direct"],
    ]
    assert [[row.iri for row in path] for path in journeys(rows, parents, change, 0, 2, 40, arrive_by=True)] == [
        ["feeder", "valid transfer"],
        ["direct"],
    ]


def test_stay_on_same_trip_through_skipped_platform_call() -> None:
    """A skipped stop prevents boarding and alighting but allows through travel."""
    first = replace(_edge("a", 0, 0, 3, 10, 20), arrival_skipped=True)
    second = replace(_edge("b", 0, 3, 2, 21, 30, 2), departure_skipped=True)
    canceled = replace(_edge("c", 1, 0, 2, 12, 15), canceled=True)
    parents, change = (-1, -1, -1, 1), (0, 10, 0, 0)
    assert journeys([first, second, canceled], parents, change, 0, 2, 10) == [[first, second]]
    assert journeys([first, second], parents, change, 0, 2, 30, arrive_by=True) == [[first, second]]
    assert journeys([first, second], parents, change, 1, 2, 10) == []
    assert journeys([first, second], parents, change, 0, 1, 10) == []


def test_scan_prefers_direct_journey_with_same_arrival() -> None:
    """Avoid listing earlier feeder trains dominated by a later direct trip."""
    rows = [
        _edge("feeder", 0, 0, 1, 10, 20),
        _edge("transfer", 1, 1, 2, 25, 35),
        _edge("direct", 2, 0, 2, 22, 35),
    ]
    assert [[row.iri for row in path] for path in journeys(rows, (-1,) * 3, (0,) * 3, 0, 2, 10)] == [["direct"]]
