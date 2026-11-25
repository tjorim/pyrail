"""Check the connection scan against an exhaustive search on small random networks."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from itertools import pairwise
import random

import pytest

from pyrail.cdn.realtime import Connection
from pyrail.cdn.routing import journeys
from pyrail.cdn.transfers import FORBIDDEN, IN_SEAT, MINIMUM_TIME, TIMED, TransferRule

_DAY = 20261124
_SEEDS = range(500)


@dataclass(frozen=True)
class _Network:
    rows: list[Connection]
    parents: list[int]
    change: list[int]
    rules: list[TransferRule]
    stations: int

    def station(self, stop: int) -> int:
        parent = self.parents[stop]
        return stop if parent == -1 else parent


def _network(seed: int, *, rules: bool, canceled: bool) -> _Network:
    random_ = random.Random(seed)
    stations = random_.randint(3, 6)
    parents = [-1] * stations
    for _ in range(random_.randint(0, 3)):
        parents.append(random_.randrange(stations))
    change = [random_.choice([0, 0, 3, 8]) for _ in parents]
    rows = []
    for trip in range(random_.randint(4, 9)):
        path = random_.sample(range(stations), random_.randint(2, min(5, stations)))
        stops = [random_.choice([s, *[i for i, p in enumerate(parents) if p == s]]) for s in path]
        clock = random_.randint(0, 60)
        delay = 0
        for sequence, (origin, destination) in enumerate(pairwise(stops), start=1):
            departure = clock + random_.randint(0, 4)
            arrival = departure + random_.randint(2, 15)
            clock = arrival
            row = Connection(
                f"t{trip}.{sequence}",
                trip,
                _DAY,
                origin,
                destination,
                sequence,
                sequence + 1,
                departure,
                arrival,
                int(random_.random() < 0.1),
                int(random_.random() < 0.1),
            )
            if canceled:
                # Delays only grow along a trip, so effective times keep their order.
                delay += random_.choice([0, 0, 0, 2, 5])
                departure_delay = delay
                delay += random_.choice([0, 0, 0, 2, 5])
                row = replace(
                    row,
                    departure_delay=departure_delay,
                    arrival_delay=delay,
                    canceled=random_.random() < 0.05,
                    departure_skipped=random_.random() < 0.05,
                    arrival_skipped=random_.random() < 0.05,
                )
            rows.append(row)
    trips = max(row.trip_index for row in rows) + 1
    selected = []
    if rules:
        for _ in range(random_.randint(1, 4)):
            before, after = random_.randrange(trips), random_.randrange(trips)
            kind = random_.choice([TIMED, MINIMUM_TIME, FORBIDDEN, IN_SEAT])
            selected.append(
                TransferRule(
                    None, None, before, after, None, None, kind, random_.choice([0, 6, 20]) if kind == 2 else None
                )
            )
    return _Network(rows, parents, change, selected, stations)


def _can_board(row: Connection) -> bool:
    return not row.canceled and row.pickup_type != 1 and not row.departure_skipped


def _can_alight(row: Connection) -> bool:
    return not row.canceled and row.drop_off_type != 1 and not row.arrival_skipped


def _minimum(network: _Network, before: Connection, after: Connection) -> int | None:
    """Return the interchange wait, following the published selector precedence."""
    station = network.station(after.departure_stop)
    if network.station(before.arrival_stop) != station:
        return None
    matches = [
        rule
        for rule in network.rules
        if rule.kind != IN_SEAT and rule.from_trip == before.trip_index and rule.to_trip == after.trip_index
    ]
    if not matches:
        return network.change[station]
    rule = next((rule for rule in matches if rule.kind == FORBIDDEN), matches[0])
    return {FORBIDDEN: None, TIMED: 0, MINIMUM_TIME: rule.minimum}.get(rule.kind)


def _search(  # noqa: C901
    network: _Network, source: int, target: int, start: int, deadline: int = 10**9
) -> list[tuple[int, int, int]]:
    """Enumerate every legal journey as (arrival, transfers, departure)."""
    runs: dict[int, list[Connection]] = defaultdict(list)
    for row in network.rows:
        runs[row.trip_index].append(row)
    for edges in runs.values():
        edges.sort(key=lambda row: row.departure_sequence)
    in_seat = {(rule.from_trip, rule.to_trip) for rule in network.rules if rule.kind == IN_SEAT}
    results: list[tuple[int, int, int]] = []

    def ride(trip: int, index: int, transfers: int, departure: int) -> None:
        edges = runs[trip]
        for stop in range(index, len(edges)):
            current = edges[stop]
            if current.canceled or (stop > index and edges[stop - 1].arrival > current.departure):
                return
            arrived(current, trip, transfers, departure, alight=_can_alight(current))

    def arrived(current: Connection, trip: int, transfers: int, departure: int, *, alight: bool) -> None:
        station = network.station(current.arrival_stop)
        if alight and station == target:
            if current.arrival <= deadline:
                results.append((current.arrival, transfers, departure))
            return
        last = runs[trip][-1] is current
        for other, edges in runs.items():
            if other == trip:
                continue
            for position, edge in enumerate(edges):
                if network.station(edge.departure_stop) != station:
                    continue
                if last and (trip, other) in in_seat and position == 0:
                    # Staying seated does not need a drop-off or a pickup at the junction.
                    if current.arrival <= edge.departure and not edge.canceled:
                        ride(other, 0, transfers, departure)
                    continue
                wait = _minimum(network, current, edge)
                if alight and wait is not None and _can_board(edge) and current.arrival + wait <= edge.departure:
                    ride(other, position, transfers + 1, departure)

    for trip, edges in runs.items():
        for position, edge in enumerate(edges):
            if network.station(edge.departure_stop) == source and edge.departure >= start and _can_board(edge):
                ride(trip, position, 0, edge.departure)
    return results


def _best(options: Iterable[tuple[int, int, int]]) -> set[tuple[int, int, int]]:
    """Keep (departure, arrival, transfers) triples that no other beats on all three."""
    unique = set(options)
    return {
        (departure, arrival, transfers)
        for departure, arrival, transfers in unique
        if not any(
            later >= departure
            and sooner <= arrival
            and fewer <= transfers
            and (later, sooner, fewer) != (departure, arrival, transfers)
            for later, sooner, fewer in unique
        )
    }


def _expected(network: _Network, source: int, target: int, start: int, deadline: int) -> set[tuple[int, int, int]]:
    found = _search(network, source, target, start, deadline)
    return _best((departure, arrival, transfers) for arrival, transfers, departure in found)


def _found(network: _Network, paths: list[list[Connection]]) -> set[tuple[int, int, int]]:
    return {(path[0].departure, path[-1].arrival, _transfers(network, path)) for path in paths}


@pytest.mark.parametrize(("rules", "canceled"), [(False, False), (False, True), (True, True)])
@pytest.mark.parametrize("arrive_by", [False, True])
def test_scan_finds_every_best_journey(*, rules: bool, canceled: bool, arrive_by: bool) -> None:
    """Both directions return exactly the journeys no other beats in departure, arrival and transfers."""
    checked = 0
    for seed in _SEEDS:
        network = _network(seed, rules=rules, canceled=canceled)
        source, target = random.Random(seed).sample(range(network.stations), 2)
        # Search from a random time of day, or back from a random deadline.
        start, deadline = random.Random(seed).randint(0, 50), random.Random(seed + 1).randint(40, 140)
        found = journeys(
            network.rows,
            network.parents,
            network.change,
            source,
            target,
            deadline if arrive_by else start,
            arrive_by=arrive_by,
            limit=1000,
            slack=10**9,
            transfer_rules=network.rules,
        )
        expected = _expected(network, source, target, 0 if arrive_by else start, deadline if arrive_by else 10**9)
        assert _found(network, found) == expected, seed
        checked += bool(expected)
    assert checked > _SEEDS.stop // 4


def _transfers(network: _Network, path: list[Connection]) -> int:
    """Count boardings after the first, except in-seat links between the end and start of two runs."""
    in_seat = {(rule.from_trip, rule.to_trip) for rule in network.rules if rule.kind == IN_SEAT}
    ends = {
        trip: max(row.departure_sequence for row in network.rows if row.trip_index == trip)
        for trip in {row.trip_index for row in network.rows}
    }
    return sum(
        a.trip_index != b.trip_index
        and not (
            (a.trip_index, b.trip_index) in in_seat
            and a.departure_sequence == ends[a.trip_index]
            and b.departure_sequence == 1
            and network.station(a.arrival_stop) == network.station(b.departure_stop)
        )
        for a, b in pairwise(path)
    )
