"""Bounded caching for the spike's prepared connection windows (not a routing API)."""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from pyrail.cdn.arrow import ArrowError
from pyrail.cdn.cache import DecodedTableCache


@dataclass(frozen=True)
class PreparedWindow:
    connections: tuple
    departures: tuple
    pages: int


def _sources(pages, files, start, end):
    selected = []
    for metadata, file in zip(pages, files, strict=True):
        low = datetime.fromisoformat(metadata["minDepartureTime"].replace("Z", "+00:00")).timestamp()
        high = datetime.fromisoformat(metadata["maxDepartureTime"].replace("Z", "+00:00")).timestamp()
        if high < start or low >= end:
            continue
        path = Path(file).resolve()
        stat = path.stat()
        signature = stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
        serialized = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        selected.append((path, signature, serialized))
    return tuple(selected)


class PreparedConnectionCache:
    """Caller-owned LRU; immutable windows keyed by release, time range and page versions.

    Fresh lookups stat relevant files and serialize their metadata, without reading Arrow
    or building/sorting tuples. Bounds count windows, not bytes. Old snapshots held by
    callers survive eviction/clear. Use external synchronization across threads.
    """

    def __init__(self, max_windows=2, decoded_cache=None):
        if max_windows <= 0:
            raise ValueError("max_windows must be positive")
        self.max_windows = max_windows
        self.decoded_cache = decoded_cache if decoded_cache is not None else DecodedTableCache()
        self.hits = self.misses = 0
        self._entries = OrderedDict()

    def prepare(self, pages, files, start, end, *, release_id):
        if start >= end:
            raise ValueError("window start must precede end")
        sources = _sources(pages, files, start, end)
        key = release_id, start, end, sources
        if key in self._entries:
            self.hits += 1
            self._entries.move_to_end(key)
            return self._entries[key]
        self.misses += 1
        from planner_spike import decode_pages

        # Use captured metadata; mutations to caller dictionaries cannot alter a cached key.
        captured = [json.loads(source[2]) for source in sources]
        paths = [source[0] for source in sources]
        connections, count = decode_pages(captured, paths, start, end, self.decoded_cache)
        connections.sort(key=lambda row: row[0])
        window = PreparedWindow(tuple(connections), tuple(row[0] for row in connections), count)
        if _sources(pages, files, start, end) != sources:
            raise ArrowError("connection pages changed during preparation; retry after refresh")
        self._entries[key] = window
        if len(self._entries) > self.max_windows:
            self._entries.popitem(last=False)
        return window

    def clear(self):
        """Release prepared windows; the separately owned decoded cache remains intact."""
        self._entries.clear()

    def __len__(self):
        return len(self._entries)
