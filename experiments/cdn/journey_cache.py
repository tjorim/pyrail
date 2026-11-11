"""Bounded result reuse for the spike's earliest-arrival queries, not full itineraries."""

from collections import OrderedDict


class JourneyResultCache:
    """LRU of immutable arrival timestamps (including unreachable results).

    Keys include a prepared snapshot's unique version, a copy of transfer times,
    stop count, endpoints, departure and scan options. Keys retain only the version
    token, not the large connection window. Scope is one caller/process; concurrent
    threads require external synchronization. Realtime is not part of this spike.
    """

    def __init__(self, max_results=128):
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        self.max_results = max_results
        self.hits = self.misses = 0
        self._entries = OrderedDict()

    def earliest_arrival(self, window, min_transfer, n_stops, source, target, departure, *, early_stop=True):
        """Reuse a result for an already validated, immutable prepared snapshot."""
        transfers = tuple(min_transfer)
        key = window.version, transfers, n_stops, source, target, departure, early_stop
        if key in self._entries:
            self.hits += 1
            self._entries.move_to_end(key)
            return self._entries[key]
        self.misses += 1
        from planner_spike import earliest_arrival

        result = earliest_arrival(
            window.connections, window.departures, transfers, n_stops, source, target, departure, early_stop=early_stop
        )
        self._entries[key] = result
        if len(self._entries) > self.max_results:
            self._entries.popitem(last=False)
        return result

    def query(
        self,
        windows,
        pages,
        files,
        start,
        end,
        *,
        release_id,
        min_transfer,
        n_stops,
        source,
        target,
        departure,
        early_stop=True,
    ):
        """Validate the current page/window versions before looking up a journey result."""
        window = windows.prepare(pages, files, start, end, release_id=release_id)
        return self.earliest_arrival(window, min_transfer, n_stops, source, target, departure, early_stop=early_stop)

    def clear(self):
        """Release result entries; hit/miss counters remain cumulative."""
        self._entries.clear()

    def __len__(self):
        return len(self._entries)
