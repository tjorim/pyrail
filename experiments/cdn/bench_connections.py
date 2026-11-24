"""Time and memory of CdnBackend.get_connections on the live CDN (#258, #247).

Run: uv run --locked python experiments/cdn/bench_connections.py [--repeat 3] [--write results.json]

Each query runs in a fresh process so peak RSS belongs to that query alone. "cold" is the first call (manifest,
page downloads, Arrow decoding, realtime fetch, scan). "warm" is the next call on the same backend, which reuses
the cached snapshot. Phases are measured by wrapping the loader, realtime merge and journey builder.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from zoneinfo import ZoneInfo

from _common import rss_mb, version

QUERIES = {
    "short": ("BE.NMBS.008812005", "BE.NMBS.008821006"),  # Brussels-North to Antwerpen-Centraal
    "long": ("BE.NMBS.008891702", "BE.NMBS.008866001"),  # Oostende to Arlon
    "arrive-by": ("BE.NMBS.008813003", "BE.NMBS.008892007"),  # Brussels-Central to Gent-Sint-Pieters
}


async def _worker(name: str, selection: str, *, trace: bool) -> dict:
    from aiohttp import ClientSession  # noqa: PLC0415

    from pyrail import CdnBackend, IRail  # noqa: PLC0415
    from pyrail.cdn import backend as backend_module  # noqa: PLC0415
    from pyrail.cdn.realtime import RealtimeLoader  # noqa: PLC0415
    from pyrail.cdn.timetable import TimetableLoader  # noqa: PLC0415

    phases: dict[str, float] = {}

    def timed(label: str, function):
        if asyncio.iscoroutinefunction(function):

            async def wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return await function(*args, **kwargs)
                finally:
                    phases[label] = phases.get(label, 0) + time.perf_counter() - start

        else:

            def wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return function(*args, **kwargs)
                finally:
                    phases[label] = phases.get(label, 0) + time.perf_counter() - start

        return wrapper

    TimetableLoader.load = timed("load", TimetableLoader.load)
    RealtimeLoader.connections = timed("realtime", RealtimeLoader.connections)
    backend_module.build_connections = timed("route", backend_module.build_connections)

    origin, destination = QUERIES[name]
    tomorrow = datetime.now(ZoneInfo("Europe/Brussels")) + timedelta(days=1)
    date, hour = tomorrow.strftime("%d%m%y"), "0900"
    result = {"query": name, "selection": selection}
    async with ClientSession() as session, IRail(backend=CdnBackend(session=session)) as client:
        for label in ("cold", "warm"):
            phases.clear()
            if trace and label == "cold":
                tracemalloc.start()
            start = time.perf_counter()
            response = await client.get_connections(origin, destination, date, hour, timesel=selection)
            elapsed = time.perf_counter() - start
            result[label] = {
                "total_ms": round(elapsed * 1000, 1),
                "phases_ms": {key: round(value * 1000, 1) for key, value in phases.items()},
                "journeys": len(response.connections or ()),
            }
            if trace and label == "cold":
                result["python_peak_mb"] = round(tracemalloc.get_traced_memory()[1] / 2**20, 1)
                tracemalloc.stop()
            result[f"rss_after_{label}_mb"] = rss_mb()
    result["peak_rss_mb"] = rss_mb()
    return result


def _run(args: argparse.Namespace) -> None:
    runs = []
    for name in QUERIES:
        selection = "arrival" if name == "arrive-by" else "departure"
        samples = []
        for _ in range(args.repeat):
            command = [sys.executable, __file__, "--worker", name, selection]
            samples.append(json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout))
        runs.append({"query": name, "selection": selection, "samples": samples})
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "machine": platform.platform(),
        "python": platform.python_version(),
        "cpus": os.cpu_count(),
        "pyrail": version("pyrail"),
        "runs": runs,
    }
    for run in runs:
        cold = [sample["cold"]["total_ms"] for sample in run["samples"]]
        warm = [sample["warm"]["total_ms"] for sample in run["samples"]]
        rss = [sample["peak_rss_mb"] for sample in run["samples"]]
        python = [sample.get("python_peak_mb") for sample in run["samples"]]
        phases = run["samples"][0]["cold"]["phases_ms"]
        print(
            f"{run['query']:>9} ({run['selection']}): cold {statistics.median(cold):.0f} ms, "
            f"warm {statistics.median(warm):.0f} ms, peak RSS {max(rss)} MiB, "
            f"journeys {run['samples'][0]['cold']['journeys']}, cold phases {phases}, python heap {python[0]}"
        )
    if args.write:
        Path(args.write).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--write")
    parser.add_argument("--worker", nargs=2, metavar=("QUERY", "SELECTION"))
    parser.add_argument("--trace", action="store_true", help="also report tracemalloc's Python heap peak")
    options = parser.parse_args()
    if options.worker:
        print(json.dumps(asyncio.run(_worker(*options.worker, trace=options.trace))))
    else:
        _run(options)
