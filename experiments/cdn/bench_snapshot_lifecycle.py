"""Per-query validation versus refresh-event-owned immutable snapshots.

Run: uv run python experiments/cdn/bench_snapshot_lifecycle.py data --write results.json
Uses local completed samples, no downloader/network calls. Publication and result misses
are reported separately from repeated query hits. Each time window uses a fresh process.
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
from snapshot_lifecycle import SnapshotSession


def timed(call, repeat=1):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter_ns()
        result = call()
        samples.append(round((time.perf_counter_ns() - start) / 1e6, 6))
    return result, {"samples_ms": samples, "median_ms": statistics.median(samples)}


def worker(data, hours, repeat):
    sample = json.loads((data / "sample.json").read_text())
    pages = [item["metadata"] for item in sample["pages"]]
    files = [data / "pages" / item["file"] for item in sample["pages"]]
    start = int(
        datetime.fromisoformat(sample["date"] + "T08:00:00").replace(tzinfo=ZoneInfo("Europe/Brussels")).timestamp()
    )
    end = start + hours * 3600
    session = SnapshotSession()
    baseline = JourneyResultCache()
    before_rss = rss_mb()
    token = session.begin_refresh()
    snapshot, initial_publication = timed(lambda: session.publish(token, data, start, end))
    index = {iri.rsplit("/", 1)[-1]: i for i, iri in enumerate(snapshot.stops["iri"])}
    queries = [
        ("short", index["008814001"], index["008821006"]),
        ("long", index["008891702"], snapshot.stops["name"].index("Arlon")),
    ]
    records = []
    for label, source, target in queries:

        def validated():
            return baseline.query(
                session.windows,
                pages,
                files,
                start,
                end,
                release_id=snapshot.release_id,
                min_transfer=snapshot.transfers,
                n_stops=snapshot.n_stops,
                source=source,
                target=target,
                departure=start,
            )

        def event_driven():
            return session.query(source, target, start)

        initial_checked, checked_miss = timed(validated)
        initial_event, event_miss = timed(event_driven)
        checked, checked_hit = timed(validated, repeat)
        event, event_hit = timed(event_driven, repeat)
        assert initial_checked == initial_event == checked == event
        records.append(
            {
                "query": label,
                "arrival": event,
                "validated_initial_miss": checked_miss,
                "event_initial_miss": event_miss,
                "validated_hit": checked_hit,
                "event_hit": event_hit,
            }
        )
    token, invalidation = timed(session.begin_refresh)
    assert session.current is None and len(session.results) == 0
    try:
        session.query(queries[0][1], queries[0][2], start)
    except RuntimeError:
        blocked_during_refresh = True
    else:
        raise AssertionError("query allowed during refresh")
    replacement, republication = timed(lambda: session.publish(token, data, start, end))
    assert replacement.generation > snapshot.generation
    assert replacement.window.version is not snapshot.window.version
    assert len(session.results) == 0
    after_event = []
    for label, source, target in queries:
        result, first = timed(lambda: session.query(source, target, start))
        assert result == next(item["arrival"] for item in records if item["query"] == label)
        after_event.append({"query": label, "first_result_after_event": first})
    return {
        "hours": hours,
        "pages": snapshot.window.pages,
        "connections": len(snapshot.window.connections),
        "queries": records,
        "initial_publication": initial_publication,
        "invalidation": invalidation,
        "no_change_republication": republication,
        "after_event": after_event,
        "blocked_during_refresh": blocked_during_refresh,
        "generations": [snapshot.generation, replacement.generation],
        "event_result_cache": {
            "entries": len(session.results),
            "hits": session.results.hits,
            "misses": session.results.misses,
        },
        "rss_before_mb": before_rss,
        "rss_peak_mb": rss_mb(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dir", nargs="?", default="data")
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--write", type=Path)
    parser.add_argument("--worker", type=int, choices=(24, 48), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be positive")
    data = data_dir([args.dir])
    if args.worker:
        print(json.dumps(worker(data, args.worker, args.repeat)))
        return
    results = []
    for hours in (24, 48):
        completed = subprocess.run(
            [sys.executable, __file__, str(data), "--worker", str(hours), "--repeat", str(args.repeat)],
            check=True,
            capture_output=True,
            text=True,
        )
        results.append(json.loads(completed.stdout))
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "repeat": args.repeat,
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "release": json.loads((data / "manifest.jsonld").read_text())["releaseId"],
        "results": results,
        "scope": "One fresh process per window; identical earliest-arrival queries for both paths. "
        "Event-owned query hits perform no filesystem checks. Cold publication, invalidation, "
        "no-change republication and first result misses are separate. Local completed sample; "
        "no HTTP download, realtime overlay or full itinerary. All writers must notify lifecycle.",
    }
    output = json.dumps(report, indent=2) + "\n"
    print(output, end="")
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(output)


if __name__ == "__main__":
    main()
