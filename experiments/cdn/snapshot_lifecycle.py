"""Explicit refresh events for no-filesystem queries against immutable spike snapshots."""

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path

from journey_cache import JourneyResultCache
from prepared_cache import PreparedConnectionCache
from pyrail.cdn.arrow import ArrowError
from pyrail.cdn.cache import DecodedTableCache


def _fingerprints(paths):
    result = []
    for path in paths:
        stat = path.stat()
        result.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(result)


@dataclass(frozen=True)
class PublishedSnapshot:
    generation: int
    release_id: str
    start: int
    end: int
    window: object
    stops: object
    transfers: tuple
    n_stops: int


class SnapshotSession:
    """Single-owner lifecycle: invalidate before writes; publish only a complete refresh.

    Queries are synchronous and do no filesystem checks. All writers must use refresh()
    or the begin/publish/fail event protocol. Unannounced external edits are intentionally
    not detected. One event loop/owner is required; concurrent threads need a lock around
    the entire lifecycle. No stale fallback or realtime overlay is implemented.
    """

    def __init__(self, max_windows=2, max_results=128):
        self.decoded = DecodedTableCache()
        self.windows = PreparedConnectionCache(max_windows=max_windows, decoded_cache=self.decoded)
        self.results = JourneyResultCache(max_results=max_results)
        self._current = None
        self._pending = None
        self.generation = 0
        self._refresh_lock = asyncio.Lock()

    @property
    def current(self):
        """Return the immutable published snapshot, or None while unavailable."""
        return self._current

    def begin_refresh(self):
        """Invalidate queries before changing files; return a unique refresh ticket."""
        self.generation += 1
        token = object()
        self._pending = token
        self._current = None
        self.results.clear()
        return token

    def fail_refresh(self, token):
        """A failed/cancelled current refresh stays unavailable; stale failures do nothing."""
        if self._pending is not None and token is self._pending:
            self._pending = None
            self._current = None
            return True
        return False

    def publish(self, token, data, start, end):
        """Validate files and prepare a replacement, then publish with one assignment."""
        if self._pending is None or token is not self._pending:
            raise RuntimeError("superseded or completed refresh ticket")
        try:
            data = Path(data)
            watched = [data / "manifest.jsonld", data / "sample.json", data / "stops.arrow"]
            before = _fingerprints(watched)
            from planner_spike import load

            stops, pages, files = load(data, self.decoded)
            sample = json.loads((data / "sample.json").read_text())
            if (
                not pages
                or datetime.fromisoformat(pages[0]["minDepartureTime"].replace("Z", "+00:00")).timestamp() > start
                or datetime.fromisoformat(pages[-1]["maxDepartureTime"].replace("Z", "+00:00")).timestamp() < end
            ):
                raise ValueError("sample does not cover the requested window")
            prepared = self.windows.prepare(pages, files, start, end, release_id=sample["releaseId"])
            if _fingerprints(watched) != before:
                raise ArrowError("snapshot metadata or stops changed during publication")
            if token is not self._pending:
                raise RuntimeError("refresh was superseded during publication")
            transfers = tuple(stops["minTransferTime"])
            count = len(stops["iri"])
            if len(transfers) != count:
                raise ValueError("transfer times do not match stop count")
            # Even a no-change refresh gets a new result version; old tokens cannot hit.
            candidate = PublishedSnapshot(
                self.generation, sample["releaseId"], start, end, replace(prepared), stops, transfers, count
            )
        except BaseException:
            self.fail_refresh(token)
            raise
        self._current = candidate
        self._pending = None
        return candidate

    async def refresh(self, data, date, pages, start, end, *, concurrency=4):
        """Own the downloader's write lifecycle, including failure/cancellation events."""
        async with self._refresh_lock:
            token = self.begin_refresh()
            try:
                from fetch_data import download_async

                await download_async(Path(data), date, pages, concurrency=concurrency)
                return self.publish(token, data, start, end)
            except BaseException:
                self.fail_refresh(token)
                raise

    def query(self, source, target, departure, *, early_stop=True):
        """Read only a published snapshot and its result cache; never stat or read files."""
        snapshot = self._current
        if snapshot is None:
            raise RuntimeError("no published snapshot; a successful refresh is required")
        if not snapshot.start <= departure < snapshot.end:
            raise ValueError("departure lies outside the published window")
        if not 0 <= source < snapshot.n_stops or not 0 <= target < snapshot.n_stops:
            raise ValueError("source or target lies outside the published stop table")
        return self.results.earliest_arrival(
            snapshot.window, snapshot.transfers, snapshot.n_stops, source, target, departure, early_stop=early_stop
        )
