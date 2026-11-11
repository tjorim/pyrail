"""Explicit refresh events, atomic publication and no-I/O query behavior."""

import asyncio
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pyarrow as pa
from pyarrow import ipc

from pyrail.cdn.arrow import ArrowError
from snapshot_lifecycle import SnapshotSession
from test_prepared_cache import write_page


class SnapshotLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        (self.data / "pages").mkdir()
        self.page = self.data / "pages" / "p0.arrow"
        write_page(self.page, (10,))
        self.metadata = {
            "epochSeconds": 0,
            "minDepartureTime": "1970-01-01T00:00:00Z",
            "maxDepartureTime": "1970-01-01T00:01:00Z",
        }
        self.write_release("v1")
        self.write_stops([0, 0])
        self.session = SnapshotSession()

    def write_release(self, release):
        (self.data / "manifest.jsonld").write_text(json.dumps({"releaseId": release}))
        (self.data / "sample.json").write_text(
            json.dumps({"releaseId": release, "pages": [{"file": "p0.arrow", "metadata": self.metadata}]})
        )

    def write_stops(self, transfers):
        table = pa.table({"iri": ["source", "target"], "minTransferTime": transfers})
        sink = BytesIO()
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
        (self.data / "stops.arrow").write_bytes(sink.getvalue())

    def publish(self):
        return self.session.publish(self.session.begin_refresh(), self.data, 0, 60)

    def test_initial_unavailability_and_queries_need_no_filesystem_even_on_miss(self):
        with self.assertRaises(RuntimeError):
            self.session.query(0, 1, 0)
        self.publish()
        with (
            patch.object(Path, "stat", side_effect=AssertionError("stat")),
            patch.object(Path, "read_bytes", side_effect=AssertionError("read")),
            patch.object(self.session.windows, "prepare", side_effect=AssertionError("prepare")),
        ):
            self.assertEqual(self.session.query(0, 1, 0), 15)
            self.assertEqual(self.session.query(0, 1, 0), 15)
        self.assertEqual((self.session.results.hits, self.session.results.misses), (1, 1))

    def test_refresh_invalidates_before_writes_and_publishes_new_generation(self):
        first = self.publish()
        self.session.query(0, 1, 0)
        token = self.session.begin_refresh()
        self.assertIsNone(self.session.current)
        self.assertEqual(len(self.session.results), 0)
        with self.assertRaises(RuntimeError):
            self.session.query(0, 1, 0)
        write_page(self.page, (20,))
        self.write_release("v2")
        second = self.session.publish(token, self.data, 0, 60)
        self.assertGreater(second.generation, first.generation)
        self.assertIsNot(second.window.version, first.window.version)
        self.assertEqual(second.release_id, "v2")
        self.assertEqual(self.session.query(0, 1, 0), 25)
        self.assertEqual(first.window.connections[0][0], 10)

    def test_no_change_refresh_still_cannot_reuse_old_result_generation(self):
        first = self.publish()
        self.session.query(0, 1, 0)
        second = self.publish()
        self.assertIsNot(first.window.version, second.window.version)
        self.assertEqual(len(self.session.results), 0)
        self.session.query(0, 1, 0)
        self.assertEqual(self.session.results.misses, 2)

    def test_failed_publication_remains_unavailable_until_successful_retry(self):
        self.publish()
        self.page.write_bytes(b"corrupt")
        with self.assertRaises(ArrowError):
            self.publish()
        with self.assertRaises(RuntimeError):
            self.session.query(0, 1, 0)
        write_page(self.page, (30,))
        self.publish()
        self.assertEqual(self.session.query(0, 1, 0), 35)

    def test_incomplete_sample_and_release_mismatch_cannot_publish(self):
        self.publish()
        (self.data / "sample.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.publish()
        self.assertIsNone(self.session.current)
        self.write_release("v1")
        (self.data / "manifest.jsonld").write_text(json.dumps({"releaseId": "v2"}))
        with self.assertRaisesRegex(ValueError, "different releases"):
            self.publish()
        self.assertIsNone(self.session.current)
        self.write_release("v2")
        self.publish()
        self.assertEqual(self.session.current.release_id, "v2")

    def test_superseded_completion_and_failure_cannot_overwrite_newer_state(self):
        old = self.session.begin_refresh()
        new = self.session.begin_refresh()
        current = self.session.publish(new, self.data, 0, 60)
        with self.assertRaises(RuntimeError):
            self.session.publish(old, self.data, 0, 60)
        self.assertFalse(self.session.fail_refresh(old))
        self.assertIs(self.session.current, current)
        self.assertEqual(self.session.query(0, 1, 0), 15)

    def test_missing_and_completed_tickets_cannot_clear_published_state(self):
        token = self.session.begin_refresh()
        current = self.session.publish(token, self.data, 0, 60)
        for invalid in (None, token):
            with self.assertRaises(RuntimeError):
                self.session.publish(invalid, self.data, 0, 60)
            self.assertFalse(self.session.fail_refresh(invalid))
            self.assertIs(self.session.current, current)

    def test_owned_refreshes_serialize_disk_writers(self):
        async def exercise():
            entered = asyncio.Event()
            release = asyncio.Event()
            active = peak = calls = 0

            async def download(*args, **kwargs):
                nonlocal active, peak, calls
                calls += 1
                current = calls
                active += 1
                peak = max(peak, active)
                if current == 1:
                    entered.set()
                    await release.wait()
                write_page(self.page, (10 * current,))
                active -= 1

            with patch("fetch_data.download_async", side_effect=download):
                first = asyncio.create_task(self.session.refresh(self.data, "1970-01-01", 1, 0, 60))
                await entered.wait()
                second = asyncio.create_task(self.session.refresh(self.data, "1970-01-01", 1, 0, 60))
                await asyncio.sleep(0)
                self.assertEqual(calls, 1)
                release.set()
                await asyncio.gather(first, second)
            self.assertEqual(peak, 1)
            self.assertEqual(self.session.query(0, 1, 0), 25)

        asyncio.run(exercise())

    def test_snapshot_metadata_change_during_publication_is_rejected(self):
        prepare = self.session.windows.prepare

        def change(*args, **kwargs):
            result = prepare(*args, **kwargs)
            self.write_stops([5, 0])
            return result

        with (
            patch.object(self.session.windows, "prepare", side_effect=change),
            self.assertRaisesRegex(ArrowError, "changed during"),
        ):
            self.publish()
        self.assertIsNone(self.session.current)

    def test_stop_values_are_published_together_and_query_bounds_are_checked(self):
        self.publish()
        self.write_stops([5, 0])
        current = self.publish()
        self.assertEqual(current.transfers, (5, 0))
        with self.assertRaises(ValueError):
            self.session.query(0, 1, 60)
        with self.assertRaises(ValueError):
            self.session.query(0, 99, 0)
        with self.assertRaises(ValueError):
            self.session.query(-1, 1, 0)
        with self.assertRaises(ValueError):
            self.session.publish(self.session.begin_refresh(), self.data, 0, 61)

    def test_unannounced_external_edits_require_explicit_refresh_notification(self):
        self.publish()
        self.assertEqual(self.session.query(0, 1, 0), 15)
        write_page(self.page, (20,))
        self.assertEqual(self.session.query(0, 1, 0), 15)  # Immutable published snapshot, not a filesystem watcher.
        self.publish()
        self.assertEqual(self.session.query(0, 1, 0), 25)

    def test_owned_downloader_refresh_announces_start_success_failure_and_cancellation(self):
        self.publish()

        async def success(*args, **kwargs):
            with self.assertRaises(RuntimeError):
                self.session.query(0, 1, 0)
            write_page(self.page, (20,))

        with patch("fetch_data.download_async", side_effect=success):
            asyncio.run(self.session.refresh(self.data, "1970-01-01", 1, 0, 60))
        self.assertEqual(self.session.query(0, 1, 0), 25)
        for failure in (OSError("network failed"), asyncio.CancelledError()):
            with self.subTest(failure=type(failure)), patch("fetch_data.download_async", side_effect=failure):
                with self.assertRaises(type(failure)):
                    asyncio.run(self.session.refresh(self.data, "1970-01-01", 1, 0, 60))
                self.assertIsNone(self.session.current)
        self.publish()
        self.assertEqual(self.session.query(0, 1, 0), 25)


if __name__ == "__main__":
    unittest.main()
