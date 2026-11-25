"""Transfer selectors from a Linked Connections timetable."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .timetable import Table

IN_SEAT = 4
FORBIDDEN = 3
MINIMUM_TIME = 2
TIMED = 1


@dataclass(frozen=True, slots=True)
class TransferRule:
    """A directed rule matching optional stop, trip and route selectors."""

    from_stop: int | None
    to_stop: int | None
    from_trip: int | None
    to_trip: int | None
    from_route: int | None
    to_route: int | None
    kind: int
    minimum: int | None

    def reversed(self) -> TransferRule:
        """Swap both ends for a backward scan."""
        return TransferRule(
            self.to_stop,
            self.from_stop,
            self.to_trip,
            self.from_trip,
            self.to_route,
            self.from_route,
            self.kind,
            self.minimum,
        )

    @property
    def specificity(self) -> tuple[int, int, int, bool]:
        """Prefer trip selectors, then route and stop selectors."""
        return (
            int(self.from_trip is not None) + int(self.to_trip is not None),
            int(self.from_route is not None) + int(self.to_route is not None),
            int(self.from_stop is not None) + int(self.to_stop is not None),
            self.kind == FORBIDDEN,
        )


def read_transfer_rules(table: Table) -> list[TransferRule]:
    """Decode the timetable's transfer rows."""
    return [
        TransferRule(*values)
        for values in zip(
            table["fromStopIdx"],
            table["toStopIdx"],
            table["fromTripIdx"],
            table["toTripIdx"],
            table["fromRouteIdx"],
            table["toRouteIdx"],
            table["transferType"],
            table["minTransferTime"],
            strict=True,
        )
    ]


class TransferRules:
    """Look up applicable transfer rules without scanning the entire table."""

    def __init__(self, rules: Sequence[TransferRule], routes: Sequence[int], parents: Sequence[int]) -> None:
        """Index rules by the outbound station and, for linked runs, the outbound trip."""
        self._routes = routes
        self._parents = parents
        self._station: dict[int | None, list[TransferRule]] = defaultdict(list)
        self._arrivals: dict[int, set[int]] = defaultdict(set)
        self._linked: dict[int, list[TransferRule]] = defaultdict(list)
        self._rule_trips = {trip for rule in rules for trip in (rule.from_trip, rule.to_trip) if trip is not None}
        self._rule_routes = {route for rule in rules for route in (rule.from_route, rule.to_route) if route is not None}
        for rule in rules:
            if rule.kind == IN_SEAT and rule.to_trip is not None:
                self._linked[rule.to_trip].append(rule)
                continue
            target = None if rule.to_stop is None else parents[rule.to_stop]
            self._station[target].append(rule)
            if target is not None and rule.from_stop is not None:
                self._arrivals[target].add(parents[rule.from_stop])

    def arrival_stations(self, station: int) -> set[int]:
        """Return the boarding station and explicit connecting stations."""
        return {station} | self._arrivals.get(station, set())

    def constrained(self, trip: int) -> bool:
        """Report whether any rule names the trip or its route, so it cannot be treated like its peers."""
        return trip in self._rule_trips or self._route(trip) in self._rule_routes

    def linked(self, trip: int) -> Sequence[TransferRule]:
        """Return possible in-seat predecessors for a trip."""
        return self._linked.get(trip, ())

    def matches(self, rule: TransferRule, before: int, after: int, origin: int, destination: int) -> bool:
        """Match both ends, allowing station-level selectors to cover platforms."""
        return (
            rule.from_stop in (None, origin, self._parents[origin])
            and rule.to_stop in (None, destination, self._parents[destination])
            and rule.from_trip in (None, before)
            and rule.to_trip in (None, after)
            and rule.from_route in (None, self._route(before))
            and rule.to_route in (None, self._route(after))
        )

    def minimum(self, before: int, after: int, origin: int, destination: int, default: int) -> int | None:
        """Return the applicable wait, or None when the transfer is forbidden."""
        station = self._parents[destination]
        external = self._parents[origin] != station
        rules = (*self._station.get(station, ()), *self._station.get(None, ()))
        rule = max(
            (rule for rule in rules if self.matches(rule, before, after, origin, destination)),
            key=lambda rule: rule.specificity,
            default=None,
        )
        if rule is None:
            return None if external else default
        if rule.kind == FORBIDDEN:
            return None
        if rule.kind == TIMED:
            return 0
        if rule.kind == MINIMUM_TIME:
            return rule.minimum
        return None if external else default

    def _route(self, trip: int) -> int | None:
        return self._routes[trip] if self._routes else None
