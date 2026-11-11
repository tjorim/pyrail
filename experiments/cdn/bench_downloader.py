"""Time the real downloader with a primed ETag cache and the original API.

Run: uv run python experiments/cdn/bench_downloader.py --date 2026-11-12 --pages 12 --write results.json
Uses a separate sample/cache directory and performs one CDN priming run, then three
warm runs. API requests use pyrail's public client, with a prime per journey and
one-second spacing. Timings include validation and disk writes / model decoding. Use --compare-transports
to compare sequential urllib, pooled sequential aiohttp, and pooled bounded concurrency.
"""

import argparse
import asyncio
from collections import Counter
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from unittest.mock import patch
from urllib.error import HTTPError

import aiohttp

import fetch_data
from pyrail import IRail
from pyrail.cdn.arrow import read_table


def download(directory, date, pages, transport="aiohttp", concurrency=4):
    requests = []
    original_open = fetch_data.urlopen

    class Response:
        def __init__(self, response, record):
            self.response = response
            self.record = record
            self.headers = response.headers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.response.close()

        def read(self):
            body = self.response.read()
            self.record["body_bytes"] += len(body)
            return body

    def record_open(request, **kwargs):
        record = {"url": request.full_url, "conditional": request.has_header("If-none-match"), "body_bytes": 0}
        requests.append(record)
        try:
            response = original_open(request, **kwargs)
        except HTTPError as error:
            record["status"] = error.code
            raise
        record["status"] = response.status
        return Response(response, record)

    connections = {"created": 0, "reused": 0}
    trace = aiohttp.TraceConfig()

    async def request_start(session, context, params):
        context.record = {"url": str(params.url), "conditional": "If-None-Match" in params.headers, "body_bytes": 0}
        requests.append(context.record)

    async def request_end(session, context, params):
        context.record["status"] = params.response.status

    async def chunk_received(session, context, params):
        context.record["body_bytes"] += len(params.chunk)

    async def connection_created(session, context, params):
        connections["created"] += 1

    async def connection_reused(session, context, params):
        connections["reused"] += 1

    trace.on_request_start.append(request_start)
    trace.on_request_end.append(request_end)
    trace.on_response_chunk_received.append(chunk_received)
    trace.on_connection_create_end.append(connection_created)
    trace.on_connection_reuseconn.append(connection_reused)

    start = time.perf_counter()
    with redirect_stdout(StringIO()):
        if transport == "urllib":
            with patch("fetch_data.urlopen", side_effect=record_open):
                fetch_data.download_sequential(directory, date, pages)
        else:
            asyncio.run(fetch_data.download_async(directory, date, pages, concurrency, trace_configs=[trace]))
    return {
        "ms": round(1000 * (time.perf_counter() - start), 3),
        "connections": connections if transport == "aiohttp" else None,
        "statuses": dict(Counter(str(r["status"]) for r in requests)),
        "conditional_requests": sum(r["conditional"] for r in requests),
        "body_bytes": sum(r["body_bytes"] for r in requests),
        "requests": requests,
    }


async def api_samples(directory, date, repeat):
    stops = read_table((directory / "stops.arrow").read_bytes())
    arlon = stops["iri"][stops["name"].index("Arlon")].rsplit("/", 1)[-1]
    queries = [("short", "008814001", "008821006"), ("long", "008891702", arlon)]
    records = []
    trace = aiohttp.TraceConfig()
    current = {}

    async def request_end(session, context, params):
        current.update(
            status=params.response.status,
            conditional="If-None-Match" in params.headers,
            etag=params.response.headers.get("ETag"),
        )

    async def chunk_received(session, context, params):
        current["body_bytes"] += len(params.chunk)

    trace.on_request_end.append(request_end)
    trace.on_response_chunk_received.append(chunk_received)
    async with aiohttp.ClientSession(trace_configs=[trace]) as session:
        async with IRail(session=session, max_retries=0) as client:
            for iteration in range(repeat + 1):
                for label, source, target in queries:
                    current = {"query": label, "prime": iteration == 0, "body_bytes": 0}
                    start = time.perf_counter()
                    result = await client.get_connections(
                        source, target, date=datetime.fromisoformat(date).strftime("%d%m%y"), time="0800"
                    )
                    current["ms"] = round(1000 * (time.perf_counter() - start), 3)
                    current["journeys"] = len(result.connections) if result is not None else None
                    current["first_arrival"] = (
                        int(result.connections[0].arrival.time.timestamp())
                        if result is not None and result.connections
                        else None
                    )
                    records.append(current.copy())
                    await asyncio.sleep(1)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=Path("data/downloader-benchmark"))
    parser.add_argument("--date", default=(datetime.now(UTC) + timedelta(days=1)).date().isoformat())
    parser.add_argument("--pages", type=int, default=12)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--write", type=Path)
    parser.add_argument("--transport", choices=("aiohttp", "urllib"), default="aiohttp")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--compare-transports", action="store_true")
    args = parser.parse_args()
    if args.pages <= 0 or args.repeat <= 0 or args.concurrency <= 0:
        parser.error("--pages, --repeat and --concurrency must be positive")
    modes = [(args.transport, args.concurrency)]
    if args.compare_transports:
        modes = [("urllib", 1), ("aiohttp", 1), ("aiohttp", args.concurrency)]
        modes = list(dict.fromkeys(modes))
    variants = []
    for transport, concurrency in modes:
        label = f"{transport}-{concurrency}"
        print(f"Priming {label} (excluded from warm results)...", file=sys.stderr, flush=True)
        prime = download(args.dir, args.date, args.pages, transport, concurrency)
        warm = []
        for index in range(args.repeat):
            print(f"Warm {label} run {index + 1}/{args.repeat}...", file=sys.stderr, flush=True)
            warm.append(download(args.dir, args.date, args.pages, transport, concurrency))
        variants.append(
            {
                "transport": transport,
                "concurrency": concurrency,
                "prime": prime,
                "warm": warm,
                "median_ms": statistics.median(r["ms"] for r in warm),
            }
        )
    print("Measuring public API client...", file=sys.stderr, flush=True)
    api = asyncio.run(api_samples(args.dir, args.date, args.repeat))
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "release": json.loads((args.dir / "manifest.jsonld").read_text())["releaseId"],
        "query_date": args.date,
        "pages": args.pages,
        "repeat": args.repeat,
        "cdn_variants": variants,
        "api": api,
        "median_ms": {
            **{f"{v['transport']}-{v['concurrency']}": v["median_ms"] for v in variants},
            **{
                label: statistics.median(r["ms"] for r in api if r["query"] == label and not r["prime"])
                for label in ("short", "long")
            },
        },
        "scope": "CDN: full sample refresh, HTTP plus disk cache reads/checks/writes, no Arrow decoding/routing. "
        "API: public IRail.get_connections, HTTP plus JSON/model parsing, shared session, "
        "ETag support enabled, no retries. API primes and one-second pacing excluded from warm medians. "
        "Response body bytes exclude HTTP headers and TLS; API aiohttp bytes may be decompressed. "
        "CDN variants share the same disk cache, prime before measurement, and create a fresh session per "
        "refresh. aiohttp reuses connections within each refresh; urllib is the original baseline.",
    }
    output = json.dumps(report, indent=2) + "\n"
    print(output, end="")
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(output)


if __name__ == "__main__":
    main()
