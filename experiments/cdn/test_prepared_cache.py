"""Prepared-window reuse and invalidation using small real Arrow pages."""

from dataclasses import FrozenInstanceError
from io import BytesIO
import operator
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pyarrow as pa
from pyarrow import ipc

from prepared_cache import PreparedConnectionCache
from pyrail.cdn.arrow import ArrowError


def write_page(path, departures=(20, 10, 40)):
    count = len(departures)
    table = pa.table(
        {
            "departureTimeOffset": list(departures),
            "arrivalTimeOffset": [d + 5 for d in departures],
            "departureStopIdx": [0] * count,
            "arrivalStopIdx": [1] * count,
            "tripIdx": list(range(count)),
            "serviceDate": [1] * count,
            "pickupType": [0] * count,
            "dropOffType": [0] * count,
        }
    )
    sink = BytesIO()
    with ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table)
    path.write_bytes(sink.getvalue())


class PreparedCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "page.arrow"
        write_page(self.path)
        self.pages = [
            {
                "epochSeconds": 0,
                "minDepartureTime": "1970-01-01T00:00:00Z",
                "maxDepartureTime": "1970-01-01T00:01:00Z",
                "@id": "release/page.arrow",
            }
        ]
        self.cache = PreparedConnectionCache()

    def prepare(self, start=0, end=30, release="v1"):
        return self.cache.prepare(self.pages, [self.path], start, end, release_id=release)

    def test_hit_needs_no_file_read_decode_or_rebuild(self):
        first = self.prepare()
        self.assertEqual(first.departures, (10, 20))
        self.assertEqual(first.pages, 1)
        with (
            patch("planner_spike.decode_pages", side_effect=AssertionError("rebuild")),
            patch.object(Path, "read_bytes", side_effect=AssertionError("read")),
        ):
            self.assertIs(self.prepare(), first)
        with self.assertRaises(TypeError):
            operator.setitem(first.connections, 0, ())
        with self.assertRaises(FrozenInstanceError):
            first.pages = 99
        self.assertEqual((self.cache.hits, self.cache.misses), (1, 1))

    def test_time_range_and_release_are_part_of_key(self):
        first = self.prepare()
        second = self.prepare(end=50)
        self.assertEqual(second.departures, (10, 20, 40))
        self.assertIsNot(first, second)
        self.assertIsNot(self.prepare(end=50, release="v2"), second)
        self.assertIsNot(self.prepare(start=15, end=50, release="v2"), second)

    def test_changed_metadata_cannot_reuse_old_epoch(self):
        first = self.prepare(end=200)
        self.pages[0]["epochSeconds"] = 100
        second = self.prepare(end=200)
        self.assertEqual(first.departures, (10, 20, 40))
        self.assertEqual(second.departures, (110, 120, 140))
        self.assertIsNot(first, second)

    def test_changed_file_and_same_name_replacement_invalidate(self):
        first = self.prepare()
        write_page(self.path, (15, 25))
        self.assertEqual(self.prepare().departures, (15, 25))
        replacement = self.path.with_name("replacement.arrow")
        write_page(replacement, (11, 21))
        replacement.replace(self.path)
        self.assertEqual(self.prepare().departures, (11, 21))
        self.assertEqual(first.departures, (10, 20))

    def test_missing_or_corrupt_file_does_not_return_old_window(self):
        self.prepare()
        self.path.write_bytes(b"bad page")
        with self.assertRaises(ArrowError):
            self.prepare()
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.prepare()
        write_page(self.path, (5,))
        self.assertEqual(self.prepare().departures, (5,))

    def test_lru_and_clear_bound_retained_windows(self):
        first = self.prepare()
        second = self.prepare(end=50)
        self.assertIs(self.prepare(), first)
        self.prepare(end=60)
        self.assertEqual(len(self.cache), 2)
        self.assertIsNot(self.prepare(end=50), second)
        self.cache.clear()
        self.assertEqual(len(self.cache), 0)
        self.assertIsNot(self.prepare(), first)

    def test_change_during_preparation_is_not_published(self):
        from planner_spike import decode_pages

        def change(*args, **kwargs):
            result = decode_pages(*args, **kwargs)
            write_page(self.path, (12,))
            return result

        with (
            patch("planner_spike.decode_pages", side_effect=change),
            self.assertRaisesRegex(ArrowError, "changed during"),
        ):
            self.prepare()
        self.assertEqual(len(self.cache), 0)
        self.assertEqual(self.prepare().departures, (12,))

    def test_bounds_mismatched_inputs_and_empty_window(self):
        with self.assertRaises(ValueError):
            PreparedConnectionCache(max_windows=0)
        with self.assertRaises(ValueError):
            self.prepare(start=10, end=10)
        with self.assertRaises(ValueError):
            self.cache.prepare(self.pages, [], 0, 30, release_id="v1")
        self.assertEqual(self.prepare(start=100, end=200).connections, ())


if __name__ == "__main__":
    unittest.main()
