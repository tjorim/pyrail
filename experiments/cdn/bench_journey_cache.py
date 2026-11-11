"""Repeated earliest-arrival queries: scans versus result hits, with version-check costs visible.

Run: uv run python experiments/cdn/bench_journey_cache.py data --write results.json
Uses separate processes for 24/48-hour windows. No network requests or realtime overlay.
"""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from _common import data_dir, rss_mb
from journey_cache import JourneyResultCache
from planner_spike import earliest_arrival, load
from prepared_cache import PreparedConnectionCache
from pyrail.cdn.cache import DecodedTableCache


def timed(call, repeat):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter_ns()
        result = call()
        samples.append(round((time.perf_counter_ns() - start) / 1e6, 6))
    return result, {"samples_ms": samples, "median_ms": statistics.median(samples)}


def worker(data, hours, repeat):
    decoded = DecodedTableCache()
    windows = PreparedConnectionCache(decoded_cache=decoded)
    results = JourneyResultCache()
    sample = json.loads((data / "sample.json").read_text())
    stops, pages, files = load(data, decoded)
    start = int(
        datetime.fromisoformat(sample["date"] + "T08:00:00").replace(tzinfo=ZoneInfo("Europe/Brussels")).timestamp()
    )
    end = start + hours * 3600
    if (
        datetime.fromisoformat(pages[0]["minDepartureTime"].replace("Z", "+00:00")).timestamp() > start
        or datetime.fromisoformat(pages[-1]["maxDepartureTime"].replace("Z", "+00:00")).timestamp() < end
    ):
        raise ValueError("downloaded sample does not cover the query window")
    baseline_rss = rss_mb()

    def prepare():
        return windows.prepare(pages, files, start, end, release_id=sample["releaseId"])

    snapshot, preparation = timed(prepare, 1)
    index = {iri.rsplit("/", 1)[-1]: i for i, iri in enumerate(stops["iri"])}
    transfers = stops["minTransferTime"] + (0,)
    count = len(stops["iri"]) + 1
    queries = [
        ("short", index["008814001"], index["008821006"]),
        ("long", index["008891702"], stops["name"].index("Arlon")),
        ("unreachable", index["008814001"], count - 1),
    ]
    records = []
    for label, source, target in queries:

        def scan():
            return earliest_arrival(snapshot.connections, snapshot.departures, transfers, count, source, target, start)

        def checked_scan():
            current = prepare()
            return earliest_arrival(current.connections, current.departures, transfers, count, source, target, start)

        def hit():
            return results.earliest_arrival(snapshot, transfers, count, source, target, start)

        def checked_hit():
            return results.query(
                windows,
                pages,
                files,
                start,
                end,
                release_id=sample["releaseId"],
                min_transfer=transfers,
                n_stops=count,
                source=source,
                target=target,
                departure=start,
            )

        expected, baseline = timed(scan, repeat)
        checked, checked_baseline = timed(checked_scan, repeat)
        first, miss = timed(hit, 1)
        cached, hot = timed(hit, repeat)
        validated, checked_hot = timed(checked_hit, repeat)
        assert expected == checked == first == cached == validated
        records.append(
            {
                "query": label,
                "arrival": expected,
                "scan": baseline,
                "validated_scan": checked_baseline,
                "initial_result_miss": miss,
                "result_hit": hot,
                "validated_result_hit": checked_hot,
            }
        )
    return {
        "hours": hours,
        "pages": snapshot.pages,
        "connections": len(snapshot.connections),
        "initial_window_preparation": preparation,
        "queries": records,
        "result_cache": {"entries": len(results), "hits": results.hits, "misses": results.misses},
        "window_cache": {"entries": len(windows), "hits": windows.hits, "misses": windows.misses},
        "rss_before_mb": baseline_rss,
        "rss_peak_mb": rss_mb(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dir", nargs="?", default="data")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--write", type=Path)
    parser.add_argument("--worker", type=int, choices=(24, 48), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be positive")
    data = data_dir([args.dir])
    if args.worker:
        print(json.dumps(worker(data, args.worker, args.repeat)))
        return
    records = []
    for hours in (24, 48):
        completed = subprocess.run(
            [sys.executable, __file__, str(data), "--worker", str(hours), "--repeat", str(args.repeat)],
            check=True,
            capture_output=True,
            text=True,
        )
        records.append(json.loads(completed.stdout))
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "repeat": args.repeat,
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "release": json.loads((data / "manifest.jsonld").read_text())["releaseId"],
        "results": records,
        "scope": "Same prepared snapshot and queries for baseline and result reuse. Raw hit timings assume "
        "an already validated snapshot; validated timings include current page metadata/file-stat "
        "checks. Initial preparation and first result miss are separate. No HTTP/realtime/full itinerary.",
    }
    output = json.dumps(report, indent=2) + "\n"
    print(output, end="")
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(output)


if __name__ == "__main__":
    main()
