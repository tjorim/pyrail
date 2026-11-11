"""Bounded, process-local caching for decoded Arrow files."""

from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .arrow import ArrowError, read_table

__all__ = ["DecodedTableCache"]


def _signature(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class DecodedTableCache:
    """LRU cache of immutable decoded tables, invalidated by file metadata changes.

    Hits perform a stat check, without reading or hashing the Arrow bytes. Atomic
    file replacement, in-place writes and ordinary timestamp changes invalidate an
    entry. This is not a file-integrity checker. Returned column tuples and their
    mapping are shared and read-only. The cache is scoped to one caller/process;
    entries are bounded by count, not bytes, and concurrent threads need external
    synchronization. No module-global cache retains timetable data implicitly.
    """

    def __init__(self, max_entries: int = 16) -> None:
        """Create an empty cache retaining at most max_entries decoded tables."""
        if max_entries <= 0:
            msg = "max_entries must be positive"
            raise ValueError(msg)
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0
        self._entries: OrderedDict[Path, tuple[tuple[int, int, int, int, int], Mapping[str, tuple[Any, ...]]]] = (
            OrderedDict()
        )

    def read(self, path: str | Path) -> Mapping[str, tuple[Any, ...]]:
        """Read a table, reusing its immutable columns while its file is unchanged.

        Missing files and read errors propagate. Malformed Arrow raises ArrowError;
        errors are never cached or replaced by an older table.
        """
        resolved = Path(path).resolve()
        try:
            signature = _signature(resolved)
        except FileNotFoundError:
            self._entries.pop(resolved, None)
            raise
        entry = self._entries.get(resolved)
        if entry is not None:
            if entry[0] == signature:
                self.hits += 1
                self._entries.move_to_end(resolved)
                return entry[1]
            del self._entries[resolved]
        self.misses += 1
        data = resolved.read_bytes()
        if _signature(resolved) != signature:
            msg = "Arrow file changed while being read; retry after the refresh completes"
            raise ArrowError(msg)
        table = MappingProxyType({name: tuple(values) for name, values in read_table(data).items()})
        self._entries[resolved] = signature, table
        if len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return table

    def clear(self) -> None:
        """Release cached tables; hit/miss counters remain cumulative."""
        self._entries.clear()

    def __len__(self) -> int:
        """Return the number of retained tables."""
        return len(self._entries)
