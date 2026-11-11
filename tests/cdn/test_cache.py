"""Decoded-file cache behavior across refreshes and consumer reuse."""

from io import BytesIO
import operator
import os
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pyarrow as pa
from pyarrow import ipc
import pytest

from pyrail.cdn.arrow import ArrowError, read_table
from pyrail.cdn.cache import DecodedTableCache


def _write(path: Path, values: list[int]) -> None:
    table = pa.table({"number": values})
    sink = BytesIO()
    with ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table)
    path.write_bytes(sink.getvalue())


def test_hit_needs_no_read_or_decode_and_result_is_immutable(tmp_path: Path) -> None:
    """Reuse the same safe snapshot without opening the file again."""
    path = tmp_path / "table.arrow"
    _write(path, [1, 2])
    cache = DecodedTableCache()
    expected = read_table(path.read_bytes())
    first = cache.read(path)
    with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected read")):
        assert cache.read(path) is first
    assert {key: list(values) for key, values in first.items()} == expected
    with pytest.raises(TypeError):
        operator.setitem(cast("Any", first), "number", ())
    with pytest.raises(TypeError):
        operator.setitem(cast("Any", first["number"]), 0, 99)
    assert (cache.hits, cache.misses) == (1, 1)


def test_atomic_replacement_invalidates_even_with_same_size_and_mtime(tmp_path: Path) -> None:
    """Refreshed release data cannot reuse a snapshot from the previous inode."""
    path = tmp_path / "table.arrow"
    _write(path, [1, 2])
    cache = DecodedTableCache()
    first = cache.read(path)
    previous = path.stat()
    replacement = tmp_path / "replacement.arrow"
    _write(replacement, [3, 4])
    os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    replacement.replace(path)
    assert path.stat().st_size == previous.st_size
    assert path.stat().st_mtime_ns == previous.st_mtime_ns
    second = cache.read(path)
    assert second["number"] == (3, 4)
    assert first["number"] == (1, 2)
    assert second is not first


def test_in_place_update_and_missing_file_do_not_return_stale_values(tmp_path: Path) -> None:
    """In-place edits invalidate, and removing a cached file is still an error."""
    path = tmp_path / "table.arrow"
    _write(path, [1, 2])
    cache = DecodedTableCache()
    cache.read(path)
    _write(path, [5, 6])
    assert cache.read(path)["number"] == (5, 6)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        cache.read(path)
    assert len(cache) == 0


def test_bad_refresh_is_not_cached_and_can_recover(tmp_path: Path) -> None:
    """A failed decode cannot substitute a previous valid table."""
    path = tmp_path / "table.arrow"
    _write(path, [1])
    cache = DecodedTableCache()
    cache.read(path)
    path.write_bytes(b"corrupt")
    with pytest.raises(ArrowError):
        cache.read(path)
    assert len(cache) == 0
    _write(path, [2])
    assert cache.read(path)["number"] == (2,)


def test_lru_eviction_and_explicit_clear_release_entries(tmp_path: Path) -> None:
    """Recently used pages survive eviction; clear forces a decode next time."""
    paths = [tmp_path / f"{index}.arrow" for index in range(3)]
    for index, path in enumerate(paths):
        _write(path, [index])
    cache = DecodedTableCache(max_entries=2)
    first = cache.read(paths[0])
    evicted = cache.read(paths[1])
    assert cache.read(paths[0]) is first
    cache.read(paths[2])
    assert len(cache) == 2
    assert cache.read(paths[1]) is not evicted
    assert cache.misses == 4
    cache.clear()
    assert len(cache) == 0
    assert cache.read(paths[0]) is not first
    assert cache.misses == 5


def test_change_during_read_is_rejected(tmp_path: Path) -> None:
    """Do not attach a decoded snapshot to the wrong file identity."""
    path = tmp_path / "table.arrow"
    _write(path, [1])
    read = Path.read_bytes

    def replace_during_read(target: Path) -> bytes:
        data = read(target)
        _write(target, [2])
        return data

    cache = DecodedTableCache()
    with patch.object(Path, "read_bytes", replace_during_read), pytest.raises(ArrowError, match="changed while"):
        cache.read(path)
    assert len(cache) == 0


def test_capacity_must_be_positive() -> None:
    """Reject a cache configuration that cannot retain any table."""
    with pytest.raises(ValueError, match="positive"):
        DecodedTableCache(max_entries=0)
