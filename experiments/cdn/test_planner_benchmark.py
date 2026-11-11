"""Small correctness checks for the benchmark's simplified routing model.

Run: uv run python -m unittest discover -s experiments/cdn -p 'test_*.py'
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from planner_benchmark import departure_profile, latest_departure
from planner_spike import INF, decode_pages, earliest_arrival, load


def connection(dep, arr, source, target, trip, pickup=0, dropoff=0):
    return dep, arr, source, target, trip, 1, pickup, dropoff


class ScanTests(unittest.TestCase):
    def test_sample_mapping_is_used_instead_of_a_hardcoded_date(self):
        with TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "stops.arrow").write_bytes(b"")
            (data / "manifest.jsonld").write_text(json.dumps({"releaseId": "test"}))
            metadata = {"epochSeconds": 123}
            (data / "sample.json").write_text(
                json.dumps(
                    {"releaseId": "test", "date": "2027-01-02", "pages": [{"file": "p7.arrow", "metadata": metadata}]}
                )
            )
            with patch("planner_spike.read_table", return_value={}):
                _, pages, files = load(data)
            self.assertEqual(pages, [metadata])
            self.assertEqual(files, [data / "pages" / "p7.arrow"])

    def test_missing_or_mismatched_sample_is_rejected(self):
        with TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "stops.arrow").write_bytes(b"")
            (data / "manifest.jsonld").write_text(json.dumps({"releaseId": "new"}))
            with patch("planner_spike.read_table", return_value={}):
                with self.assertRaisesRegex(ValueError, "missing sample.json"):
                    load(data)
                (data / "sample.json").write_text(json.dumps({"releaseId": "old"}))
                with self.assertRaisesRegex(ValueError, "different releases"):
                    load(data)

    def test_only_departures_inside_the_query_window_are_kept(self):
        page = {
            "epochSeconds": 0,
            "minDepartureTime": "1970-01-01T00:00:00Z",
            "maxDepartureTime": "1970-01-01T00:01:00Z",
        }
        table = {
            "departureTimeOffset": [5, 10, 29, 30],
            "arrivalTimeOffset": [6, 11, 30, 31],
            "departureStopIdx": [0] * 4,
            "arrivalStopIdx": [1] * 4,
            "tripIdx": [0] * 4,
            "serviceDate": [1] * 4,
            "pickupType": [0] * 4,
            "dropOffType": [0] * 4,
        }
        with patch("planner_spike.read_table", return_value=table):
            connections, pages = decode_pages([page], [Mock()], 10, 30)
        self.assertEqual([c[0] for c in connections], [10, 29])
        self.assertEqual(pages, 1)

    def test_transfer_time_and_arrive_by(self):
        connections = [
            connection(10, 20, 0, 1, 0),
            connection(24, 30, 1, 2, 1),
            connection(25, 35, 1, 2, 2),
        ]
        deps = [c[0] for c in connections]
        transfers = [0, 5, 0]
        self.assertEqual(earliest_arrival(connections, deps, transfers, 3, 0, 2, 0), 35)
        self.assertEqual(latest_departure(connections, transfers, 3, 0, 2, 35), 10)
        self.assertEqual(latest_departure(connections, transfers, 3, 0, 2, 30), -INF)

    def test_staying_on_the_same_trip_needs_no_transfer(self):
        connections = [connection(10, 20, 0, 1, 0), connection(21, 30, 1, 2, 0)]
        self.assertEqual(earliest_arrival(connections, [10, 21], [0, 5, 0], 3, 0, 2, 0), 30)
        self.assertEqual(latest_departure(connections, [0, 5, 0], 3, 0, 2, 30), 10)

    def test_profile_removes_dominated_departures(self):
        connections = [
            connection(10, 20, 0, 1, 0),
            connection(12, 18, 0, 1, 1),
            connection(15, 22, 0, 1, 2),
        ]
        profile, scans = departure_profile(connections, [10, 12, 15], [0, 0], 2, 0, 1, 0, 30)
        self.assertEqual(profile, [(12, 18), (15, 22)])
        self.assertEqual(scans, 3)
        self.assertEqual(
            earliest_arrival(connections, [10, 12, 15], [0, 0], 2, 0, 1, 0, early_stop=False),
            18,
        )

    def test_pickup_dropoff_and_unreachable_target(self):
        for forbidden in (
            connection(10, 20, 0, 1, 0, pickup=1),
            connection(10, 20, 0, 1, 0, dropoff=1),
        ):
            self.assertEqual(earliest_arrival([forbidden], [10], [0, 0], 2, 0, 1, 0), INF)
            self.assertEqual(latest_departure([forbidden], [0, 0], 2, 0, 1, 30), -INF)
        self.assertEqual(
            earliest_arrival([connection(10, 20, 0, 1, 0)], [10], [0, 0, 0], 3, 0, 2, 0),
            INF,
        )


if __name__ == "__main__":
    unittest.main()
