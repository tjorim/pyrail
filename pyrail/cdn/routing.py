"""Connection scans over an iRail timetable snapshot."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .transfers import TransferRule, TransferRules

PROFILE_SLACK = 3600
_MAX_TRANSFERS = 6

if TYPE_CHECKING:
    from .realtime import Connection


@dataclass(frozen=True, slots=True)
class _Edge:
    row: Connection
    origin: int
    destination: int
    departure: int
    arrival: int
    sequence: int
    next_sequence: int
    board: bool
    alight: bool
    from_stop: int
    to_stop: int


@dataclass(frozen=True, slots=True)
class _Path:
    edge: _Edge
    previous: _Path | None
    transfers: int
    start: int


Front = list[_Path]
"""Labels reaching one point: no label has both at least as few transfers and an at least as late start."""


def _edges(rows: Sequence[Connection], parents: Sequence[int], *, reverse: bool, scheduled: bool) -> list[_Edge]:
    stations = [index if parent == -1 else parent for index, parent in enumerate(parents)]
    result = []
    for row in rows:
        if row.canceled and not scheduled:
            continue
        origin, destination = stations[row.departure_stop], stations[row.arrival_stop]
        departure = row.scheduled_departure if scheduled else row.departure
        arrival = row.scheduled_arrival if scheduled else row.arrival
        board = row.pickup_type != 1 and (scheduled or not row.departure_skipped)
        alight = row.drop_off_type != 1 and (scheduled or not row.arrival_skipped)
        if reverse:
            result.append(
                _Edge(
                    row,
                    destination,
                    origin,
                    -arrival,
                    -departure,
                    row.arrival_sequence,
                    row.departure_sequence,
                    alight,
                    board,
                    row.arrival_stop,
                    row.departure_stop,
                )
            )
        else:
            result.append(
                _Edge(
                    row,
                    origin,
                    destination,
                    departure,
                    arrival,
                    row.departure_sequence,
                    row.arrival_sequence,
                    board,
                    alight,
                    row.departure_stop,
                    row.arrival_stop,
                )
            )
    return sorted(result, key=lambda edge: (edge.departure, edge.arrival, -edge.sequence if reverse else edge.sequence))


def _add(front: Front, path: _Path) -> None:
    """Insert a label unless an existing one is at least as good in both transfers and start."""
    for other in front:
        if other.transfers <= path.transfers and other.start >= path.start:
            return
    front[:] = [other for other in front if path.transfers > other.transfers or path.start < other.start]
    front.append(path)


def _add_inbound(front: Front, path: _Path) -> None:
    """Insert an arrival unless one is at least as early, with as few transfers and as late a start."""
    arrival = path.edge.arrival
    for other in front:
        if other.edge.arrival <= arrival and other.transfers <= path.transfers and other.start >= path.start:
            return
    front[:] = [
        other
        for other in front
        if path.edge.arrival > other.edge.arrival or path.transfers > other.transfers or path.start < other.start
    ]
    front.append(path)


def _boarding_labels(
    edge: _Edge,
    front: Front,
    station_paths: dict[int, dict[tuple[int, int, int], Front]],
    rules: TransferRules,
    change_time: int,
) -> None:
    """Add the best ways to board an edge from journeys that arrived at its station."""
    for stop in rules.arrival_stations(edge.origin):
        for inbound in station_paths.get(stop, {}).values():
            for previous in inbound:
                transfers = previous.transfers + 1
                # Test dominance and timing before the costlier transfer rules.
                if transfers > _MAX_TRANSFERS or any(
                    other.transfers <= transfers and other.start >= previous.start for other in front
                ):
                    continue
                if previous.edge.arrival > edge.departure or (
                    previous.edge.row.trip_index == edge.row.trip_index
                    and previous.edge.row.service_date == edge.row.service_date
                ):
                    continue
                minimum = rules.minimum(
                    previous.edge.row.trip_index,
                    edge.row.trip_index,
                    previous.edge.to_stop,
                    edge.from_stop,
                    change_time,
                )
                if minimum is not None and previous.edge.arrival + minimum <= edge.departure:
                    _add(front, _Path(edge, previous, transfers, previous.start))


def _linked_labels(edge: _Edge, front: Front, arrived: dict[tuple[int, int], Front], rules: TransferRules) -> None:
    for rule in rules.linked(edge.row.trip_index):
        if rule.from_trip is None:
            continue
        for previous in arrived.get((rule.from_trip, edge.row.service_date), ()):
            if (
                previous.edge.destination == edge.origin
                and previous.edge.arrival <= edge.departure
                and rules.matches(rule, rule.from_trip, edge.row.trip_index, previous.edge.to_stop, edge.from_stop)
            ):
                _add(front, _Path(edge, previous, previous.transfers, previous.start))


def _run_endpoints(
    rows: Sequence[Connection], *, reverse: bool
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], int]]:
    """Find where each run starts and ends, counting canceled connections as part of the run."""
    first: dict[tuple[int, int], int] = {}
    last: dict[tuple[int, int], int] = {}
    for row in rows:
        key = row.trip_index, row.service_date
        if reverse:
            first[key] = max(first.get(key, row.arrival_sequence), row.arrival_sequence)
            last[key] = min(last.get(key, row.departure_sequence), row.departure_sequence)
        else:
            first[key] = min(first.get(key, row.departure_sequence), row.departure_sequence)
            last[key] = max(last.get(key, row.arrival_sequence), row.arrival_sequence)
    return first, last


def _pareto(paths: Iterable[_Path]) -> list[_Path]:
    """Keep journeys that no other beats in arrival, transfers and start at once."""
    kept: list[_Path] = []
    for path in sorted(paths, key=lambda path: (path.edge.arrival, path.transfers, -path.start)):
        if not any(other.transfers <= path.transfers and other.start >= path.start for other in kept):
            kept.append(path)
    return kept


@dataclass(frozen=True, slots=True)
class _Search:
    """Edges and transfer rules shared by every scan of one query."""

    edges: Sequence[_Edge]
    departures: Sequence[int]
    change_time: Sequence[int]
    rules: TransferRules
    first: dict[tuple[int, int], int]
    last: dict[tuple[int, int], int]
    slack: int

    def scan(self, source: int, target: int, start: int) -> list[_Path]:
        """Return the journeys from the source at or after the start that are best for the target."""
        onboard: dict[tuple[int, int, int], Front] = {}
        station_paths: dict[int, dict[tuple[int, int, int], Front]] = defaultdict(dict)
        arrived: dict[tuple[int, int], Front] = {}
        reached: list[_Path] = []
        earliest: int | None = None
        for index in range(bisect_left(self.departures, start), len(self.edges)):
            edge = self.edges[index]
            if earliest is not None and edge.departure > earliest + self.slack:
                break
            key = edge.row.trip_index, edge.row.service_date
            front = self._labels(edge, key, source, onboard, station_paths, arrived)
            if not front:
                continue
            onboard[(*key, edge.next_sequence)] = front
            if edge.next_sequence == self.last[key]:
                arrived[key] = front
            if not edge.alight:
                continue
            # Trips that no rule names behave alike, so their arrivals at one stop compete directly.
            group = key if self.rules.constrained(edge.row.trip_index) else (-1, 0)
            inbound = station_paths[edge.destination].setdefault((*group, edge.to_stop), [])
            for path in front:
                _add_inbound(inbound, path)
            if edge.destination == target:
                reached.extend(front)
                earliest = edge.arrival if earliest is None else min(earliest, edge.arrival)
        return _pareto(path for path in reached if earliest is not None and path.edge.arrival <= earliest + self.slack)

    def _labels(
        self,
        edge: _Edge,
        key: tuple[int, int],
        source: int,
        onboard: dict[tuple[int, int, int], Front],
        station_paths: dict[int, dict[tuple[int, int, int], Front]],
        arrived: dict[tuple[int, int], Front],
    ) -> Front:
        front: Front = []
        previous = onboard.get((*key, edge.sequence), [])
        if previous and previous[0].edge.arrival <= edge.departure:
            front.extend(_Path(edge, path, path.transfers, path.start) for path in previous)
        if edge.board and edge.origin == source:
            _add(front, _Path(edge, None, 0, edge.departure))
        elif edge.board:
            _boarding_labels(edge, front, station_paths, self.rules, self.change_time[edge.origin])
        if edge.sequence == self.first[key]:
            _linked_labels(edge, front, arrived, self.rules)
        return front


def _rows(path: _Path, *, arrive_by: bool) -> list[Connection]:
    """List the connections of a journey in travel order."""
    rows = []
    step: _Path | None = path
    while step is not None:
        rows.append(step.edge.row)
        step = step.previous
    return rows if arrive_by else rows[::-1]


def journeys(
    rows: Sequence[Connection],
    parents: Sequence[int],
    change_time: Sequence[int],
    source: int,
    target: int,
    instant: int,
    *,
    arrive_by: bool = False,
    limit: int = 6,
    transfer_rules: Sequence[TransferRule] = (),
    routes: Sequence[int] = (),
    include_canceled: bool = False,
    slack: int = PROFILE_SLACK,
    horizon: int | None = None,
) -> list[list[Connection]]:
    """Find the journeys that are best in departure, arrival and transfers.

    Repeated scans find, for every start time, the journeys that arrive earliest for their number of
    transfers. A journey with more transfers is kept only when it arrives sooner, and one arriving later
    than ``slack`` seconds after the earliest is not searched for. Backward scans mirror this for arrive-by.
    A horizon limits the search to journeys that start, or for arrive-by end, within that many seconds of the
    instant, although they may need connections beyond it.
    """
    if source == target:
        return []
    edges = _edges(rows, parents, reverse=arrive_by, scheduled=include_canceled)
    first, last = _run_endpoints(rows, reverse=arrive_by)
    stations = [index if parent == -1 else parent for index, parent in enumerate(parents)]
    rules = TransferRules(
        [rule.reversed() for rule in transfer_rules] if arrive_by else transfer_rules, routes, stations
    )
    search = _Search(edges, [edge.departure for edge in edges], change_time, rules, first, last, slack)
    if arrive_by:
        source, target, instant = target, source, -instant
    until = None if horizon is None else instant + horizon
    found: dict[tuple[int, int, int], _Path] = {}
    while until is None or instant <= until:
        front = search.scan(source, target, instant)
        if not front:
            break
        for path in front:
            if until is None or path.start <= until:
                found.setdefault((path.start, path.edge.arrival, path.transfers), path)
        instant = min(path.start for path in front) + 1
        # Journeys that start before the next scan are final, as later scans cannot beat them.
        if sum(start < instant for start, _, _ in found) >= limit:
            break
    result = [_rows(path, arrive_by=arrive_by) for _, path in sorted(found.items())[:limit]]
    if arrive_by:
        result.reverse()
    return result
