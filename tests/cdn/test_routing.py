"""Tests for forward and arrive-by connection scans."""

from dataclasses import replace

from pyrail.cdn.realtime import Connection
from pyrail.cdn.routing import journeys
from pyrail.cdn.transfers import TransferRule


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


def test_specific_rules_preserve_alternate_feeders_in_both_directions() -> None:
    """Honor trip-specific prohibitions and route-specific minimum time."""
    rows = [
        _edge("blocked", 0, 0, 1, 10, 15),
        _edge("usable", 1, 0, 1, 11, 18),
        _edge("onward", 2, 1, 2, 20, 30),
    ]
    rules = [
        TransferRule(1, 1, None, None, 7, 8, 2, 2),
        TransferRule(1, 1, 0, 2, None, None, 3, None),
    ]
    for reverse in (False, True):
        paths = journeys(
            rows,
            (-1,) * 3,
            (0, 10, 0),
            0,
            2,
            30 if reverse else 10,
            arrive_by=reverse,
            transfer_rules=rules,
            routes=(7, 7, 8),
        )
        assert paths == [[rows[1], rows[2]]]


def test_same_vehicle_continuation_can_cross_a_trip_number_change() -> None:
    """A type 4 continuation allows staying aboard without boarding again."""
    first = replace(_edge("a", 0, 0, 1, 10, 20), drop_off_type=1)
    second = replace(_edge("b", 1, 1, 2, 21, 30), pickup_type=1)
    rule = TransferRule(None, None, 0, 1, None, None, 4, None)
    for reverse in (False, True):
        paths = journeys(
            [first, second],
            (-1,) * 3,
            (0, 10, 0),
            0,
            2,
            30 if reverse else 10,
            arrive_by=reverse,
            transfer_rules=[rule],
        )
        assert paths == [[first, second]]
    assert journeys([first, second], (-1,) * 3, (0, 10, 0), 0, 2, 10) == []


def test_explicit_timed_transfer_can_link_distinct_station_indices() -> None:
    """A timed interchange can connect two published stops across station IDs."""
    rows = [_edge("a", 0, 0, 1, 10, 20), _edge("b", 1, 2, 3, 21, 30)]
    rule = TransferRule(1, 2, None, None, None, None, 1, None)
    assert journeys(rows, (-1,) * 4, (10,) * 4, 0, 3, 10, transfer_rules=[rule]) == [rows]
