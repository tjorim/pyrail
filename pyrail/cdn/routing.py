"""Connection scans over an iRail timetable snapshot."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .transfers import TransferRule, TransferRules

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

    @property
    def rank(self) -> tuple[int, int, int]:
        return self.edge.arrival, self.transfers, -self.start


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


def _boarding_paths(
    edge: _Edge,
    station_paths: dict[int, dict[tuple[int, int], _Path]],
    rules: TransferRules,
    change_time: int,
) -> Iterable[_Path]:
    for stop in rules.arrival_stations(edge.origin):
        for previous in station_paths.get(stop, {}).values():
            # A trip can be resumed only through its consecutive onboard edges.
            if (
                previous.edge.row.trip_index == edge.row.trip_index
                and previous.edge.row.service_date == edge.row.service_date
            ):
                continue
            minimum = rules.minimum(
                previous.edge.row.trip_index, edge.row.trip_index, previous.edge.to_stop, edge.from_stop, change_time
            )
            if minimum is not None and previous.edge.arrival + minimum <= edge.departure:
                yield _Path(edge, previous, previous.transfers + 1, previous.start)


def _linked_paths(edge: _Edge, arrived: dict[tuple[int, int], _Path], rules: TransferRules) -> Iterable[_Path]:
    for rule in rules.linked(edge.row.trip_index):
        if rule.from_trip is None:
            continue
        previous = arrived.get((rule.from_trip, edge.row.service_date))
        if (
            previous is not None
            and previous.edge.destination == edge.origin
            and previous.edge.arrival <= edge.departure
            and rules.matches(rule, rule.from_trip, edge.row.trip_index, previous.edge.to_stop, edge.from_stop)
        ):
            yield _Path(edge, previous, previous.transfers, previous.start)


def _run_endpoints(
    edges: Sequence[_Edge], *, reverse: bool
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], int]]:
    first: dict[tuple[int, int], int] = {}
    last: dict[tuple[int, int], int] = {}
    for edge in edges:
        key = edge.row.trip_index, edge.row.service_date
        if reverse:
            first[key] = max(first.get(key, edge.sequence), edge.sequence)
            last[key] = min(last.get(key, edge.next_sequence), edge.next_sequence)
        else:
            first[key] = min(first.get(key, edge.sequence), edge.sequence)
            last[key] = max(last.get(key, edge.next_sequence), edge.next_sequence)
    return first, last


def _store_arrival(
    path: _Path,
    best: dict[int, _Path],
    by_inbound: dict[int, dict[tuple[int, int], _Path]],
) -> None:
    edge = path.edge
    arrivals = by_inbound[edge.destination]
    key = (edge.row.trip_index, edge.to_stop)
    previous = arrivals.get(key)
    if previous is None or path.rank < previous.rank:
        arrivals[key] = path
    previous = best.get(edge.destination)
    if previous is None or path.rank < previous.rank:
        best[edge.destination] = path


def _scan(
    edges: Sequence[_Edge],
    departures: Sequence[int],
    source: int,
    target: int,
    start: int,
    change_time: Sequence[int],
    rules: TransferRules,
    first: dict[tuple[int, int], int],
    last: dict[tuple[int, int], int],
) -> _Path | None:
    onboard: dict[tuple[int, int, int], _Path] = {}
    station: dict[int, _Path] = {}
    station_paths: dict[int, dict[tuple[int, int], _Path]] = defaultdict(dict)
    arrived: dict[tuple[int, int], _Path] = {}
    for index in range(bisect_left(departures, start), len(edges)):
        edge = edges[index]
        best = station.get(target)
        if best is not None and edge.departure > best.edge.arrival:
            break
        key = edge.row.trip_index, edge.row.service_date
        previous = onboard.get((*key, edge.sequence))
        if previous is not None and previous.edge.arrival > edge.departure:
            previous = None
        candidates = [] if previous is None else [_Path(edge, previous, previous.transfers, previous.start)]
        if edge.board and edge.origin == source:
            candidates.append(_Path(edge, None, 0, edge.departure))
        elif edge.board:
            candidates.extend(_boarding_paths(edge, station_paths, rules, change_time[edge.origin]))
        if edge.sequence == first[key]:
            candidates.extend(_linked_paths(edge, arrived, rules))
        if not candidates:
            continue
        candidate = min(candidates, key=lambda path: path.rank)
        onboard[(*key, edge.next_sequence)] = candidate
        if edge.next_sequence == last[key]:
            arrived[key] = candidate
        if edge.alight:
            _store_arrival(candidate, station, station_paths)
    return station.get(target)


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
) -> list[list[Connection]]:
    """Find successive earliest-arrival or latest-departure rail journeys."""
    if source == target:
        return []
    edges = _edges(rows, parents, reverse=arrive_by, scheduled=include_canceled)
    departures = [edge.departure for edge in edges]
    first, last = _run_endpoints(edges, reverse=arrive_by)
    stations = [index if parent == -1 else parent for index, parent in enumerate(parents)]
    rules = TransferRules(
        [rule.reversed() for rule in transfer_rules] if arrive_by else transfer_rules, routes, stations
    )
    if arrive_by:
        source, target, instant = target, source, -instant
    found = []
    for _ in range(limit):
        path = _scan(edges, departures, source, target, instant, change_time, rules, first, last)
        if path is None:
            break
        rows_for_path = []
        while path.previous is not None:
            rows_for_path.append(path.edge.row)
            path = path.previous
        rows_for_path.append(path.edge.row)
        instant = path.edge.departure + 1
        if not arrive_by:
            rows_for_path.reverse()
        found.append(rows_for_path)
    if arrive_by:
        found.reverse()
    return found
