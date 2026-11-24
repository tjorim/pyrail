"""Connection scans over an iRail timetable snapshot."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

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


@dataclass(frozen=True, slots=True)
class _Path:
    edge: _Edge
    previous: _Path | None
    transfers: int
    start: int

    @property
    def rank(self) -> tuple[int, int, int]:
        return self.edge.arrival, self.transfers, -self.start


def _edges(rows: Sequence[Connection], parents: Sequence[int], *, reverse: bool) -> list[_Edge]:
    stations = [index if parent == -1 else parent for index, parent in enumerate(parents)]
    result = []
    for row in rows:
        if row.canceled:
            continue
        origin, destination = stations[row.departure_stop], stations[row.arrival_stop]
        board = row.pickup_type != 1 and not row.departure_skipped
        alight = row.drop_off_type != 1 and not row.arrival_skipped
        if reverse:
            result.append(
                _Edge(
                    row,
                    destination,
                    origin,
                    -row.arrival,
                    -row.departure,
                    row.arrival_sequence,
                    row.departure_sequence,
                    alight,
                    board,
                )
            )
        else:
            result.append(
                _Edge(
                    row,
                    origin,
                    destination,
                    row.departure,
                    row.arrival,
                    row.departure_sequence,
                    row.arrival_sequence,
                    board,
                    alight,
                )
            )
    return sorted(result, key=lambda edge: (edge.departure, edge.arrival, -edge.sequence if reverse else edge.sequence))


def _scan(
    edges: Sequence[_Edge],
    departures: Sequence[int],
    source: int,
    target: int,
    start: int,
    change_time: Sequence[int],
) -> _Path | None:
    onboard: dict[tuple[int, int, int], _Path] = {}
    station: dict[int, _Path] = {}
    for index in range(bisect_left(departures, start), len(edges)):
        edge = edges[index]
        best = station.get(target)
        if best is not None and edge.departure > best.edge.arrival:
            break
        key = edge.row.trip_index, edge.row.service_date
        previous = onboard.get((*key, edge.sequence))
        if previous is not None and previous.edge.arrival > edge.departure:
            previous = None
        at_origin = station.get(edge.origin)
        candidate = None if previous is None else _Path(edge, previous, previous.transfers, previous.start)
        if edge.board and edge.origin == source:
            candidate = _Path(edge, None, 0, edge.departure)
        elif (
            edge.board and at_origin is not None and at_origin.edge.arrival + change_time[edge.origin] <= edge.departure
        ):
            transfer = _Path(edge, at_origin, at_origin.transfers + 1, at_origin.start)
            if candidate is None or transfer.rank < candidate.rank:
                candidate = transfer
        if candidate is None:
            continue
        onboard[(*key, edge.next_sequence)] = candidate
        existing = station.get(edge.destination)
        if edge.alight and (existing is None or candidate.rank < existing.rank):
            station[edge.destination] = candidate
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
) -> list[list[Connection]]:
    """Find successive earliest-arrival or latest-departure rail journeys."""
    if source == target:
        return []
    edges = _edges(rows, parents, reverse=arrive_by)
    departures = [edge.departure for edge in edges]
    if arrive_by:
        source, target, instant = target, source, -instant
    found = []
    for _ in range(limit):
        path = _scan(edges, departures, source, target, instant, change_time)
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
