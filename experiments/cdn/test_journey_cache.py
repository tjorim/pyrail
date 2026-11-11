"""Result-cache keys, lifecycle and source-version validation for the routing spike."""

import gc
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import weakref

from journey_cache import JourneyResultCache
from prepared_cache import PreparedConnectionCache, PreparedWindow
from test_prepared_cache import write_page


def window():
    rows = ((10, 20, 0, 1, 0, 1, 0, 0), (25, 30, 1, 2, 1, 1, 0, 0), (50, 60, 0, 2, 2, 1, 0, 0))
    return PreparedWindow(rows, tuple(row[0] for row in rows), 1)


class JourneyCacheTests(unittest.TestCase):
    def test_hit_avoids_scan(self):
        cache = JourneyResultCache()
        snapshot = window()
        self.assertEqual(cache.earliest_arrival(snapshot, [0, 5, 0], 3, 0, 2, 0), 30)
        with patch("planner_spike.earliest_arrival", side_effect=AssertionError("unexpected scan")):
            self.assertEqual(cache.earliest_arrival(snapshot, [0, 5, 0], 3, 0, 2, 0), 30)
        self.assertEqual((cache.hits, cache.misses), (1, 1))

    def test_query_parameters_and_options_are_distinct(self):
        cache = JourneyResultCache()
        snapshot = window()
        cases = [
            (3, 0, 2, 0, True, 30),
            (3, 0, 1, 0, True, 20),
            (3, 1, 2, 0, True, 30),
            (3, 0, 2, 11, True, 60),
            (4, 0, 2, 0, True, 30),
            (3, 0, 2, 0, False, 30),
        ]
        for count, source, target, departure, early_stop, expected in cases:
            self.assertEqual(
                cache.earliest_arrival(snapshot, [0, 5, 0], count, source, target, departure, early_stop=early_stop),
                expected,
            )
        self.assertEqual(cache.misses, len(cases))
        self.assertEqual(cache.hits, 0)

    def test_mutating_transfer_times_invalidates_result(self):
        cache = JourneyResultCache()
        snapshot = window()
        transfers = [0, 5, 0]
        self.assertEqual(cache.earliest_arrival(snapshot, transfers, 3, 0, 2, 0), 30)
        transfers[1] = 6
        self.assertEqual(cache.earliest_arrival(snapshot, transfers, 3, 0, 2, 0), 60)
        self.assertEqual(cache.misses, 2)

    def test_new_snapshot_has_a_new_version_even_with_equal_rows(self):
        cache = JourneyResultCache()
        first, second = window(), window()
        self.assertIsNot(first.version, second.version)
        cache.earliest_arrival(first, [0, 5, 0], 3, 0, 2, 0)
        cache.earliest_arrival(second, [0, 5, 0], 3, 0, 2, 0)
        self.assertEqual(cache.misses, 2)

    def test_unreachable_result_can_be_cached(self):
        cache = JourneyResultCache()
        snapshot = window()
        result = cache.earliest_arrival(snapshot, [0, 5, 0, 0], 4, 0, 3, 0)
        self.assertEqual(result, 10**12)
        with patch("planner_spike.earliest_arrival", side_effect=AssertionError("unexpected scan")):
            self.assertEqual(cache.earliest_arrival(snapshot, [0, 5, 0, 0], 4, 0, 3, 0), result)

    def test_results_do_not_retain_large_connection_windows(self):
        cache = JourneyResultCache()
        snapshot = window()
        reference = weakref.ref(snapshot)
        cache.earliest_arrival(snapshot, [0, 5, 0], 3, 0, 2, 0)
        del snapshot
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(len(cache), 1)

    def test_lru_capacity_clear_and_errors(self):
        with self.assertRaises(ValueError):
            JourneyResultCache(max_results=0)
        cache = JourneyResultCache(max_results=2)
        snapshot = window()
        cache.earliest_arrival(snapshot, [0, 5, 0], 3, 0, 2, 0)
        cache.earliest_arrival(snapshot, [0, 5, 0], 3, 0, 1, 0)
        cache.earliest_arrival(snapshot, [0, 5, 0], 3, 0, 2, 0)
        cache.earliest_arrival(snapshot, [0, 5, 0], 3, 0, 2, 11)
        cache.earliest_arrival(snapshot, [0, 5, 0], 3, 0, 1, 0)
        self.assertEqual((len(cache), cache.misses), (2, 4))
        cache.clear()
        with patch("planner_spike.earliest_arrival", side_effect=RuntimeError("failed scan")):
            with self.assertRaises(RuntimeError):
                cache.earliest_arrival(snapshot, [0, 5, 0], 3, 0, 2, 0)
        self.assertEqual(len(cache), 0)

    def test_query_validates_file_metadata_release_and_range_before_hit(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "page.arrow"
            write_page(path, (10,))
            pages = [
                {
                    "epochSeconds": 0,
                    "minDepartureTime": "1970-01-01T00:00:00Z",
                    "maxDepartureTime": "1970-01-01T00:01:00Z",
                }
            ]
            windows = PreparedConnectionCache()
            cache = JourneyResultCache()

            def query(release="v1", end=100):
                return cache.query(
                    windows,
                    pages,
                    [path],
                    0,
                    end,
                    release_id=release,
                    min_transfer=[0, 0],
                    n_stops=2,
                    source=0,
                    target=1,
                    departure=0,
                )

            self.assertEqual(query(), 15)
            self.assertEqual(query(), 15)
            self.assertEqual(cache.hits, 1)
            write_page(path, (20,))
            self.assertEqual(query(), 25)
            pages[0]["epochSeconds"] = 10
            self.assertEqual(query(), 35)
            self.assertEqual(query(release="v2"), 35)
            self.assertEqual(query(release="v2", end=200), 35)
            self.assertEqual(cache.misses, 5)
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                query(release="v2", end=200)


if __name__ == "__main__":
    unittest.main()
