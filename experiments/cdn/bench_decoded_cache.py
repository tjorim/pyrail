"""Compare repeated Arrow loads with a bounded decoded-table cache.

Run: uv run python experiments/cdn/bench_decoded_cache.py data --write results.json
Each mode/window runs in a fresh process. No network requests are made. Planner
memory mode rebuilds connection tuples from cached Arrow columns. Prepared mode additionally
caches immutable connection windows and departure indexes. No journey results are cached.
"""

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from _common import data_dir, files, rss_mb
from planner_spike import decode_pages, earliest_arrival, load
from prepared_cache import PreparedConnectionCache
from pyrail.cdn.arrow import read_table
from pyrail.cdn.cache import DecodedTableCache


def digest(tables):
    result = hashlib.sha256()
    for table in tables:
        for name, values in table.items():
            result.update(name.encode())
            result.update(repr(tuple(values)).encode())
    return result.hexdigest()


def timed(call):
    start = time.perf_counter()
    result = call()
    return result, round(1000 * (time.perf_counter() - start), 3)


def worker(data, mode, hours, repeat):
    paths = files(data)
    cache = DecodedTableCache(max_entries=len(paths)) if mode in ("memory", "prepared") else None
    baseline_rss = rss_mb()

    def read_all():
        return [cache.read(path) if cache is not None else read_table(path.read_bytes()) for path in paths]

    tables, prime_ms = timed(read_all)
    expected = digest(tables)
    del tables
    raw_samples = []
    for _ in range(repeat):
        tables, elapsed = timed(read_all)
        assert digest(tables) == expected
        raw_samples.append(elapsed)
        del tables
    raw_stats = {"entries": len(cache), "hits": cache.hits, "misses": cache.misses} if cache is not None else None
    sample = json.loads((data / "sample.json").read_text())
    t0 = int(
        datetime.fromisoformat(sample["date"] + "T08:00:00").replace(tzinfo=ZoneInfo("Europe/Brussels")).timestamp()
    )
    t1 = t0 + hours * 3600
    stops, pages, page_files = load(data, cache)
    if (
        datetime.fromisoformat(pages[0]["minDepartureTime"].replace("Z", "+00:00")).timestamp() > t0
        or datetime.fromisoformat(pages[-1]["maxDepartureTime"].replace("Z", "+00:00")).timestamp() < t1
    ):
        raise ValueError("sample does not cover the requested window; fetch more pages")
    index = {iri.rsplit("/", 1)[-1]: i for i, iri in enumerate(stops["iri"])}
    queries = [
        ("short", index["008814001"], index["008821006"]),
        ("long", index["008891702"], stops["name"].index("Arlon")),
    ]

    prepared_cache = PreparedConnectionCache(decoded_cache=cache) if mode == "prepared" else None

    def prepare():
        if prepared_cache is not None:
            result = prepared_cache.prepare(pages, page_files, t0, t1, release_id=sample["releaseId"])
            return result.connections, result.departures, result.pages
        connections, count = decode_pages(pages, page_files, t0, t1, cache)
        connections.sort(key=lambda c: c[0])
        return connections, [c[0] for c in connections], count

    initial_window, prepare_prime_ms = timed(prepare)
    del initial_window
    preparation = []
    searches = {name: [] for name, _, _ in queries}
    arrivals = {}
    for _ in range(repeat):
        (connections, departures, count), elapsed = timed(prepare)
        preparation.append(elapsed)
        connection_digest = hashlib.sha256(repr(tuple(connections)).encode()).hexdigest()
        for name, source, target in queries:
            arrival, elapsed = timed(
                lambda connections=connections, departures=departures: earliest_arrival(
                    connections, departures, stops["minTransferTime"], len(stops["iri"]), source, target, t0
                )
            )
            arrivals[name] = arrival
            searches[name].append(elapsed)
        rows = len(connections)
        del connections, departures
    return {
        "mode": mode,
        "hours": hours,
        "files": len(paths),
        "arrow_digest": expected,
        "prime_ms": prime_ms,
        "raw_load_samples_ms": raw_samples,
        "raw_load_median_ms": statistics.median(raw_samples),
        "raw_cache_stats": raw_stats,
        "pages": count,
        "connections": rows,
        "connection_digest": connection_digest,
        "prepare_prime_ms": prepare_prime_ms,
        "prepared_cache_stats": {
            "entries": len(prepared_cache),
            "hits": prepared_cache.hits,
            "misses": prepared_cache.misses,
        }
        if prepared_cache is not None
        else None,
        "decoded_cache_final_stats": {"entries": len(cache), "hits": cache.hits, "misses": cache.misses}
        if cache is not None
        else None,
        "prepare_samples_ms": preparation,
        "prepare_median_ms": statistics.median(preparation),
        "search_samples_ms": searches,
        "arrivals": arrivals,
        "rss_before_mb": baseline_rss,
        "rss_peak_mb": rss_mb(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dir", nargs="?", default="data")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--write", type=Path)
    parser.add_argument("--worker", choices=("uncached", "memory", "prepared"), help=argparse.SUPPRESS)
    parser.add_argument("--hours", type=int, choices=(24, 48), default=24, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeat <= 0:
        parser.error("--repeat must be positive")
    data = data_dir([args.dir])
    if args.worker:
        print(json.dumps(worker(data, args.worker, args.hours, args.repeat)))
        return
    results = []
    for hours in (24, 48):
        for mode in ("uncached", "memory", "prepared"):
            completed = subprocess.run(
                [
                    sys.executable,
                    __file__,
                    str(data),
                    "--worker",
                    mode,
                    "--hours",
                    str(hours),
                    "--repeat",
                    str(args.repeat),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            results.append(json.loads(completed.stdout))
        before = results[-3]
        for after in results[-2:]:
            for key in ("arrow_digest", "connection_digest", "arrivals"):
                assert before[key] == after[key], f"cached {key} differs from baseline"
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "repeat": args.repeat,
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "release": json.loads((data / "manifest.jsonld").read_text())["releaseId"],
        "results": results,
        "scope": "Fresh processes per mode/window; first raw load excluded from warm medians. "
        "Raw loads return all tables. First window preparation is separately timed and excluded from warm medians. "
        "memory mode rebuilds/sorts connection tuples; prepared mode reuses immutable tuples and their departure index. RSS is the process high-water mark including digest verification, "
        "cache, preparations and searches. No network or full production routing.",
    }
    output = json.dumps(report, indent=2) + "\n"
    print(output, end="")
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(output)


if __name__ == "__main__":
    main()
