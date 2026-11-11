"""ETag downloader checks against a local HTTP server; no external network required."""

import asyncio
from collections import deque
from contextlib import redirect_stdout
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import aiohttp

import fetch_data
from fetch_data import Downloader


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        with self.server.lock:
            self.server.active += 1
            self.server.peak = max(self.server.peak, self.server.active)
            self.server.ports.add(self.client_address[1])
        if self.server.delay:
            time.sleep(self.server.delay)
        try:
            self.respond()
        finally:
            with self.server.lock:
                self.server.active -= 1

    def respond(self):
        self.server.requests.append((self.path, self.headers.get("If-None-Match")))
        status, headers, body = self.server.responses.popleft()
        self.send_response_only(status)
        if "Date" not in headers:
            self.send_header("Date", self.date_time_string())
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


class FilePublicationTests(unittest.TestCase):
    def test_unchanged_file_is_not_replaced(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "data.arrow"
            path.write_bytes(b"original")
            before = path.stat()
            with patch("fetch_data._atomic_write") as write:
                self.assertFalse(fetch_data._write_if_changed(path, b"original"))
            write.assert_not_called()
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            self.assertEqual(path.stat().st_ino, before.st_ino)

    def test_missing_changed_and_same_size_corrupt_files_are_repaired(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "data.arrow"
            self.assertTrue(fetch_data._write_if_changed(path, b"original"))
            self.assertTrue(fetch_data._write_if_changed(path, b"changed"))
            self.assertEqual(path.read_bytes(), b"changed")
            path.write_bytes(b"corrupt")
            self.assertTrue(fetch_data._write_if_changed(path, b"changed"))
            self.assertEqual(path.read_bytes(), b"changed")

    def test_sample_marker_stays_hidden_until_success_and_preserves_mtime(self):
        with TemporaryDirectory() as directory:
            out = Path(directory)
            sample = {"pages": []}
            raw = b"manifest"
            fetch_data.prepare(out)
            with redirect_stdout(StringIO()):
                fetch_data.finish(out, raw, sample)
            before = (out / "sample.json").stat()
            fetch_data.prepare(out)
            self.assertFalse((out / "sample.json").exists())
            self.assertTrue((out / ".sample.previous").exists())
            # A retry following an interrupted refresh can still restore the old marker.
            fetch_data.prepare(out)
            with patch("fetch_data._atomic_write") as write, redirect_stdout(StringIO()):
                fetch_data.finish(out, raw, sample)
            write.assert_not_called()
            self.assertEqual((out / "sample.json").stat().st_mtime_ns, before.st_mtime_ns)
            self.assertEqual((out / "sample.json").stat().st_ino, before.st_ino)
            self.assertFalse((out / ".sample.previous").exists())


class FreshnessPolicyTests(unittest.TestCase):
    def test_explicit_policy_parsing(self):
        now = 1800000000
        date = formatdate(now, usegmt=True)
        cases = [
            ({"cache-control": 'PUBLIC, MAX-AGE="60"'}, {}, now + 60),
            ({"cache-control": "max-age=60, max-age=120"}, {}, now),
            ({"cache-control": "max-age=-1"}, {}, now),
            ({"cache-control": "max-age=invalid"}, {}, now),
            ({"cache-control": 'max-age="60'}, {}, now),
            ({"cache-control": "max-age=0"}, {}, now),
            ({"cache-control": "max-age=60, no-cache"}, {}, now),
            ({"cache-control": "max-age=60, no-store"}, {}, None),
            ({"cache-control": "s-maxage=60"}, {}, now),
            ({"cache-control": 'extension="a,max-age=600"'}, {}, now),
            ({"cache-control": "max-age=60"}, {"Age": "invalid"}, now),
            ({"cache-control": "max-age=60"}, {"Age": "61"}, now),
            ({"cache-control": "max-age=60", "vary": "*"}, {}, now),
            ({"cache-control": "max-age=60", "vary": "Accept-Encoding"}, {}, now + 60),
            ({"cache-control": "max-age=60", "vary": "Accept-Language"}, {}, now),
            ({"expires": formatdate(now + 30, usegmt=True)}, {}, now + 30),
            ({"expires": "invalid"}, {}, now),
            ({"cache-control": "max-age=5", "expires": formatdate(now + 60, usegmt=True)}, {}, now + 5),
        ]
        for headers, response, expected in cases:
            with self.subTest(headers=headers, response=response):
                self.assertEqual(fetch_data._fresh_until(headers, {"Date": date, **response}, now, now), expected)

    def test_request_delay_is_counted_as_age(self):
        now = 1800000000
        self.assertEqual(
            fetch_data._fresh_until(
                {"cache-control": "max-age=60"}, {"Date": formatdate(now, usegmt=True), "Age": "10"}, now - 5, now
            ),
            now + 45,
        )


class DownloaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.downloader = self.make_downloader()
        self.url = f"http://127.0.0.1:{self.server.server_port}/release-a/stops.arrow"
        self.server.requests = []
        self.server.responses = deque()
        self.server.lock = Lock()
        self.server.active = self.server.peak = 0
        self.server.ports = set()
        self.server.delay = 0

    def make_downloader(self, revalidate=False):
        return Downloader(self.directory, revalidate)

    def respond(self, body=b"original", etag='W/"v1"', status=200, headers=None):
        fields = {"ETag": etag} if etag is not None else {}
        fields.update(headers or {})
        self.server.responses.append((status, fields, body))

    def seed(self):
        self.respond()
        self.assertEqual(self.downloader.get(self.url), b"original")

    def clock(self):
        self.now = time.time()
        clock = patch("fetch_data.time", SimpleNamespace(time=lambda: self.now))
        clock.start()
        self.addCleanup(clock.stop)

    def fresh_response(self, control="max-age=10", **kwargs):
        headers = {"Cache-Control": control, "Date": formatdate(self.now, usegmt=True)}
        headers.update(kwargs.pop("headers", {}))
        self.respond(headers=headers, **kwargs)

    def test_fresh_hit_survives_restart_then_expiry_revalidates(self):
        self.clock()
        self.fresh_response()
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.now += 9
        self.assertEqual(self.make_downloader().get(self.url), b"original")
        self.assertEqual(len(self.server.requests), 1)
        self.now += 2
        self.fresh_response(status=304, body=b"")
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.assertEqual(self.server.requests[-1][1], 'W/"v1"')
        self.now += 9
        self.assertEqual(self.make_downloader().get(self.url), b"original")
        self.assertEqual(len(self.server.requests), 2)

    def test_only_expired_resource_contacts_server(self):
        self.clock()
        self.fresh_response("max-age=600")
        self.downloader.get(self.url)
        realtime = self.url + "?realtime"
        self.fresh_response("max-age=5", body=b"snapshot")
        self.downloader.get(realtime)
        self.now += 6
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.fresh_response("max-age=5", body=b"updated snapshot")
        self.assertEqual(self.downloader.get(realtime), b"updated snapshot")
        self.assertEqual(len(self.server.requests), 3)
        self.assertTrue(self.server.requests[-1][0].endswith("?realtime"))
        self.assertEqual(self.server.requests[-1][1], 'W/"v1"')

    def test_fresh_response_without_etag_can_be_reused(self):
        self.clock()
        self.fresh_response(etag=None)
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.assertEqual(self.make_downloader().get(self.url), b"original")
        self.assertEqual(len(self.server.requests), 1)
        self.now += 11
        self.fresh_response(etag=None, body=b"new")
        self.assertEqual(self.downloader.get(self.url), b"new")
        self.assertIsNone(self.server.requests[-1][1])

    def test_explicit_revalidation_bypasses_freshness(self):
        self.clock()
        self.fresh_response("max-age=600")
        self.downloader.get(self.url)
        self.respond(status=304, body=b"")
        self.assertEqual(self.make_downloader(revalidate=True).get(self.url), b"original")
        self.assertEqual(len(self.server.requests), 2)
        self.assertEqual(self.server.requests[-1][1], 'W/"v1"')

    def test_no_cache_always_revalidates(self):
        self.clock()
        self.fresh_response("max-age=600, no-cache")
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.fresh_response("max-age=600, no-cache", status=304, body=b"")
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.assertEqual(len(self.server.requests), 2)

    def test_no_store_removes_cached_body_and_validator(self):
        self.seed()
        self.clock()
        self.fresh_response("no-store, max-age=600", body=b"private")
        self.assertEqual(self.downloader.get(self.url), b"private")
        self.assertEqual(list((self.directory / ".http-cache").iterdir()), [])
        self.respond()
        self.downloader.get(self.url)
        self.assertIsNone(self.server.requests[-1][1])

    def test_age_and_date_reduce_remaining_freshness(self):
        self.clock()
        self.fresh_response("max-age=10", headers={"Age": "8"})
        self.downloader.get(self.url)
        self.now += 1
        self.downloader.get(self.url)
        self.assertEqual(len(self.server.requests), 1)
        self.now += 2
        self.fresh_response("max-age=10", headers={"Date": formatdate(self.now - 20, usegmt=True)})
        self.downloader.get(self.url)
        self.respond(body=b"new")
        self.assertEqual(self.downloader.get(self.url), b"new")
        self.assertEqual(len(self.server.requests), 3)

    def test_304_inherits_policy_but_refreshes_age(self):
        self.clock()
        self.fresh_response()
        self.downloader.get(self.url)
        self.now += 11
        self.respond(status=304, body=b"", headers={"Date": formatdate(self.now, usegmt=True)})
        self.downloader.get(self.url)
        self.now += 8
        self.downloader.get(self.url)
        self.assertEqual(len(self.server.requests), 2)

    def test_304_no_store_discards_cache(self):
        self.seed()
        self.respond(status=304, body=b"", headers={"Cache-Control": "no-store"})
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.assertEqual(list((self.directory / ".http-cache").iterdir()), [])

    def test_fresh_body_still_requires_matching_digest(self):
        self.clock()
        self.fresh_response("max-age=600")
        self.downloader.get(self.url)
        next((self.directory / ".http-cache").glob("*.body")).write_bytes(b"corrupt")
        self.respond(body=b"new")
        self.assertEqual(self.downloader.get(self.url), b"new")
        self.assertIsNone(self.server.requests[-1][1])

    def test_clock_rollback_forces_revalidation(self):
        self.clock()
        self.fresh_response("max-age=600")
        self.downloader.get(self.url)
        self.now -= 100
        self.respond(status=304, body=b"")
        self.downloader.get(self.url)
        self.assertEqual(len(self.server.requests), 2)

    def test_etag_survives_restart_and_304_reuses_body(self):
        self.seed()
        body = next((self.directory / ".http-cache").glob("*.body"))
        original_mtime = body.stat().st_mtime_ns
        self.respond(body=b"", etag=None, status=304)
        restarted = self.make_downloader()
        self.assertEqual(restarted.get(self.url), b"original")
        self.assertEqual(body.stat().st_mtime_ns, original_mtime)
        self.assertEqual([etag for _, etag in self.server.requests], [None, 'W/"v1"'])

    def test_200_with_identical_body_updates_validator_without_rewriting_body(self):
        self.seed()
        body = next((self.directory / ".http-cache").glob("*.body"))
        before = body.stat()
        self.respond(b"original", '"v2"')
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.assertEqual((body.stat().st_ino, body.stat().st_mtime_ns), (before.st_ino, before.st_mtime_ns))
        self.respond(body=b"", etag=None, status=304)
        self.downloader.get(self.url)
        self.assertEqual(self.server.requests[-1][1], '"v2"')

    def test_changed_response_replaces_body_and_validator(self):
        self.seed()
        self.respond(b"updated", '"v2"')
        self.assertEqual(self.downloader.get(self.url), b"updated")
        self.respond(body=b"", etag=None, status=304)
        self.assertEqual(self.make_downloader().get(self.url), b"updated")
        self.assertEqual(self.server.requests[-1][1], '"v2"')

    def test_304_can_refresh_validator(self):
        self.seed()
        self.respond(body=b"", etag='"v2"', status=304)
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.respond(body=b"", etag=None, status=304)
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.assertEqual(self.server.requests[-1][1], '"v2"')

    def test_200_without_etag_clears_previous_validator(self):
        self.seed()
        self.respond(b"no validator", etag=None)
        self.assertEqual(self.downloader.get(self.url), b"no validator")
        self.respond(b"next", etag=None)
        self.assertEqual(self.downloader.get(self.url), b"next")
        self.assertIsNone(self.server.requests[-1][1])

    def test_different_release_or_query_does_not_share_validator(self):
        self.seed()
        for url in (self.url.replace("release-a", "release-b"), self.url + "?variant=2"):
            self.respond(b"different")
            self.assertEqual(self.downloader.get(url), b"different")
            self.assertIsNone(self.server.requests[-1][1])

    def test_missing_or_corrupt_body_forces_unconditional_download(self):
        for damage in ("missing", "corrupt"):
            with self.subTest(damage=damage):
                self.seed()
                body = next((self.directory / ".http-cache").glob("*.body"))
                if damage == "missing":
                    body.unlink()
                else:
                    body.write_bytes(b"wrong bytes")
                self.respond(b"recovered")
                self.assertEqual(self.downloader.get(self.url), b"recovered")
                self.assertIsNone(self.server.requests[-1][1])

    def test_invalid_metadata_forces_unconditional_download(self):
        for damaged in ("{invalid", "[]", '{"url": "wrong"}'):
            with self.subTest(metadata=damaged):
                self.seed()
                metadata = next((self.directory / ".http-cache").glob("*.json"))
                metadata.write_text(damaged)
                self.respond(b"recovered")
                self.assertEqual(self.downloader.get(self.url), b"recovered")
                self.assertIsNone(self.server.requests[-1][1])

    def test_server_error_does_not_return_stale_data_or_replace_cache(self):
        self.seed()
        self.respond(b"failure", '"bad"', status=503)
        with self.assertRaises((HTTPError, aiohttp.ClientResponseError)) as caught:
            self.downloader.get(self.url)
        if isinstance(caught.exception, HTTPError):
            caught.exception.close()
        self.assertEqual(
            caught.exception.code if isinstance(caught.exception, HTTPError) else caught.exception.status, 503
        )
        self.respond(body=b"", etag=None, status=304)
        self.assertEqual(self.downloader.get(self.url), b"original")
        self.assertEqual(self.server.requests[-1][1], 'W/"v1"')

    def test_partial_cache_update_cannot_reuse_old_validator(self):
        self.seed()
        self.respond(b"updated", '"v2"')
        atomic_write = fetch_data._atomic_write

        def fail_metadata(path, data):
            if path.suffix == ".json":
                raise OSError("interrupted update")
            atomic_write(path, data)

        with patch("fetch_data._atomic_write", side_effect=fail_metadata):
            with self.assertRaisesRegex(OSError, "interrupted update"):
                self.downloader.get(self.url)
        self.respond(b"recovered", '"v3"')
        self.assertEqual(self.make_downloader().get(self.url), b"recovered")
        self.assertIsNone(self.server.requests[-1][1])

    def test_full_download_reuses_cache_and_restores_missing_sample_file(self):
        base = self.url.rsplit("/", 2)[0] + "/"
        manifest = {
            "releaseId": "test",
            "coverageStart": "2026-11-12",
            "coverageEnd": "2026-11-13",
            **{name: name + ".arrow" for name in ("stops", "routes", "trips", "transfers")},
            "irail:extensions": {"@id": "irail.json"},
            "realtime": [{"@id": base + "realtime.pb"}],
            "connections": {"pages": [{"@id": "page.arrow", "minDepartureTime": "2026-11-12T00:00:00Z"}]},
        }
        self.respond(json.dumps(manifest).encode())
        for _ in range(7):
            self.respond(b"sample bytes")
        arguments = ["fetch_data.py", str(self.directory), "--date", "2026-11-12", "--pages", "1"]
        with (
            patch("fetch_data.MANIFEST", base + "manifest.jsonld"),
            patch("sys.argv", arguments),
            redirect_stdout(StringIO()),
        ):
            fetch_data.main()
            tracked = [
                self.directory / "manifest.jsonld",
                self.directory / "stops.arrow",
                self.directory / "sample.json",
            ]
            before = {path: (path.stat().st_ino, path.stat().st_mtime_ns) for path in tracked}
            (self.directory / "pages" / "p0.arrow").unlink()
            for _ in range(8):
                self.respond(body=b"", etag=None, status=304)
            fetch_data.main()
        for path in tracked:
            self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns), before[path])
        self.assertEqual((self.directory / "pages" / "p0.arrow").read_bytes(), b"sample bytes")
        self.assertEqual(json.loads((self.directory / "sample.json").read_text())["releaseId"], "test")
        self.assertEqual([etag for _, etag in self.server.requests[:8]], [None] * 8)
        self.assertEqual([etag for _, etag in self.server.requests[8:]], ['W/"v1"'] * 8)

    def test_unsolicited_304_without_cached_body_is_an_error(self):
        self.respond(body=b"", etag='"v1"', status=304)
        with self.assertRaises((HTTPError, aiohttp.ClientResponseError)) as caught:
            self.downloader.get(self.url)
        if isinstance(caught.exception, HTTPError):
            caught.exception.close()
        self.assertFalse((self.directory / ".http-cache").exists())


class AsyncDownloaderTests(DownloaderTests):
    def make_downloader(self, revalidate=False):
        runner = asyncio.Runner()

        async def create():
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
            return session, fetch_data.AsyncDownloader(self.directory, session, revalidate)

        session, downloader = runner.run(create())

        def close():
            runner.run(session.close())
            runner.close()

        self.addCleanup(close)
        return SimpleNamespace(get=lambda url: runner.run(downloader.get(url)))

    def test_pool_reuses_connections_and_bounds_concurrency(self):
        base = self.url.rsplit("/", 2)[0] + "/"
        manifest = {
            "releaseId": "test",
            "coverageStart": "2026-11-12",
            "coverageEnd": "2026-11-13",
            **{name: name + ".arrow" for name in ("stops", "routes", "trips", "transfers")},
            "irail:extensions": {"@id": "irail.json"},
            "realtime": [{"@id": base + "realtime.pb"}],
            "connections": {"pages": [{"@id": "page.arrow", "minDepartureTime": "2026-11-12T00:00:00Z"}]},
        }
        self.respond(json.dumps(manifest).encode())
        for _ in range(7):
            self.respond(b"sample bytes")
        self.server.delay = 0.02
        with patch("fetch_data.MANIFEST", base + "manifest.jsonld"), redirect_stdout(StringIO()):
            asyncio.run(fetch_data.download_async(self.directory, "2026-11-12", 1, concurrency=2))
        self.assertEqual(self.server.peak, 2)
        self.assertEqual(len(self.server.ports), 2)
        self.assertEqual(len(self.server.requests), 8)
        self.assertTrue((self.directory / "sample.json").exists())

    def test_failed_parallel_refresh_does_not_publish_sample(self):
        base = self.url.rsplit("/", 2)[0] + "/"
        manifest = {
            "releaseId": "test",
            "coverageStart": "2026-11-12",
            "coverageEnd": "2026-11-13",
            **{name: name + ".arrow" for name in ("stops", "routes", "trips", "transfers")},
            "irail:extensions": {"@id": "irail.json"},
            "realtime": [{"@id": base + "realtime.pb"}],
            "connections": {"pages": [{"@id": "page.arrow", "minDepartureTime": "2026-11-12T00:00:00Z"}]},
        }
        (self.directory / "sample.json").write_text("old sample")
        self.respond(json.dumps(manifest).encode())
        self.respond(b"failure", status=503)
        for _ in range(6):
            self.respond(b"sample bytes")
        with patch("fetch_data.MANIFEST", base + "manifest.jsonld"), redirect_stdout(StringIO()):
            with self.assertRaises(ExceptionGroup):
                asyncio.run(fetch_data.download_async(self.directory, "2026-11-12", 1, concurrency=2))
        self.assertFalse((self.directory / "sample.json").exists())


if __name__ == "__main__":
    unittest.main()
