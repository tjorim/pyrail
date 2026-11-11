"""Reproducible #261 benchmark; each window runs in a fresh process.

Run: uv run python experiments/cdn/planner_benchmark.py data --write results.json
This measures the simplified spike, not a production router. The profile is an exact
Pareto profile for that spike's model, obtained by scanning once per source departure;
it is intentionally a baseline for assessing whether a smarter profile algorithm is needed.
"""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from _common import data_dir, rss_mb, version
from planner_spike import INF, decode_pages, earliest_arrival, load


def latest_departure(connections, min_transfer, n_stops, source, target, deadline):
    """Reverse Connection Scan for the spike's model (no footpaths or realtime)."""
    latest = [-INF] * n_stops
    latest[target] = deadline
    reached = set()
    best = -INF
    for dep, arr, dep_stop, arr_stop, trip, date, pickup, dropoff in reversed(connections):
        if dep < best:
            break
        key = trip, date
        ready = latest[arr_stop] if arr_stop == target else latest[arr_stop] - min_transfer[arr_stop]
        if key in reached or (dropoff != 1 and arr <= ready):
            reached.add(key)
            if pickup != 1 and dep > latest[dep_stop]:
                latest[dep_stop] = dep
                if dep_stop == source:
                    best = dep
    return best


def departure_profile(connections, deps, transfers, n_stops, source, target, t0, t1):
    """Return nondominated (departure, arrival) pairs for all source departures in the window."""
    departures = sorted(
        {c[0] for c in connections if c[2] == source and c[6] != 1 and t0 <= c[0] < t1},
        reverse=True,
    )
    best = INF
    profile = []
    for departure in departures:
        arrival = earliest_arrival(connections, deps, transfers, n_stops, source, target, departure)
        if arrival < best:
            profile.append((departure, arrival))
            best = arrival
    return list(reversed(profile)), len(departures)


def timed(call, repeat=5):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        result = call()
        samples.append(1000 * (time.perf_counter() - start))
    return result, {
        "best_ms": round(min(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
    }


def worker(data, hours, numpy=False):
    if numpy:
        import numpy as np

    stops, pages, files = load(data)
    sample = json.loads((data / "sample.json").read_text())
    t0 = int(
        datetime.fromisoformat(sample["date"] + "T08:00:00").replace(tzinfo=ZoneInfo("Europe/Brussels")).timestamp()
    )
    t1 = t0 + hours * 3600
    low = datetime.fromisoformat(pages[0]["minDepartureTime"].replace("Z", "+00:00")).timestamp()
    high = datetime.fromisoformat(pages[-1]["maxDepartureTime"].replace("Z", "+00:00")).timestamp()
    if low > t0 or high < t1:
        raise ValueError(f"downloaded pages do not span the {hours}-hour query window; fetch more pages")
    baseline = rss_mb()
    (connections, count), decode = timed(lambda: decode_pages(pages, files, t0, t1), repeat=1)
    connections, sort = timed(lambda: sorted(connections, key=lambda c: c[0]), repeat=1)
    conversion = None
    if numpy:
        connections, conversion = timed(lambda: np.asarray(connections, dtype=np.int64), repeat=1)
    deps = [c[0] for c in connections]
    transfers = stops["minTransferTime"]
    n_stops = len(stops["iri"])
    index = {iri.rsplit("/", 1)[-1]: i for i, iri in enumerate(stops["iri"])}
    queries = [
        ("short", index["008814001"], index["008821006"]),
        ("long", index["008891702"], stops["name"].index("Arlon")),
        ("unreachable", index["008814001"], n_stops),
    ]
    queries_out = []
    for label, source, target in queries:

        def scan(early_stop=True):
            return earliest_arrival(
                connections,
                deps,
                transfers + [0],
                n_stops + 1,
                source,
                target,
                t0,
                early_stop=early_stop,
            )

        arrival, early = timed(scan)
        full_arrival, full = timed(lambda: scan(False))
        assert arrival == full_arrival
        record = {
            "query": label,
            "arrival": int(arrival) if arrival < INF else None,
            "early_stop": early,
            "full_scan": full,
        }
        if label != "unreachable" and not numpy:
            departure, reverse = timed(lambda: latest_departure(connections, transfers, n_stops, source, target, t1))
            record.update(
                arrive_by=reverse,
                latest_departure=departure if departure > -INF else None,
            )
            if departure > -INF:
                assert earliest_arrival(connections, deps, transfers, n_stops, source, target, departure) <= t1
            (profile, scans), timing = timed(
                lambda: departure_profile(connections, deps, transfers, n_stops, source, target, t0, t1),
                repeat=1,
            )
            record.update(profile=timing, profile_scans=scans, pareto_journeys=len(profile))
        queries_out.append(record)
    return {
        "storage": "numpy-int64" if numpy else "python-tuples",
        "numpy_version": version("numpy") if numpy else None,
        "numpy_conversion": conversion,
        "hours": hours,
        "pages": count,
        "connections": len(connections),
        "decode": decode,
        "sort": sort,
        "rss_before_mb": baseline,
        "rss_peak_mb": rss_mb(),
        "queries": queries_out,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dir", nargs="?", default="data")
    parser.add_argument("--write", type=Path)
    parser.add_argument("--numpy", action="store_true", help="also probe NumPy int64 storage (requires numpy)")
    parser.add_argument("--worker", type=int, choices=[24, 48], help=argparse.SUPPRESS)
    args = parser.parse_args()
    data = data_dir([args.dir])
    if args.worker:
        print(json.dumps(worker(data, args.worker, args.numpy)))
        return
    windows = []
    for numpy in [False, True] if args.numpy else [False]:
        for hours in (24, 48):
            command = [sys.executable, __file__, str(data), "--worker", str(hours)]
            if numpy:
                command.append("--numpy")
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            windows.append(json.loads(result.stdout))
    if args.numpy:
        for plain, numpy in zip(windows[:2], windows[2:], strict=True):
            assert [q["arrival"] for q in plain["queries"]] == [q["arrival"] for q in numpy["queries"]]
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpus": os.cpu_count(),
        "release": json.loads((data / "manifest.jsonld").read_text())["releaseId"],
        "sample_date": json.loads((data / "sample.json").read_text())["date"],
        "model": "no footpaths, transfers table, realtime, or in-seat transfers; not a production router",
        "windows": windows,
    }
    output = json.dumps(report, indent=2) + "\n"
    print(output, end="")
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(output)


if __name__ == "__main__":
    main()
