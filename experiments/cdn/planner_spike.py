"""Spike for #261: is a connection-scan route planner in plain Python fast enough?

A throwaway earliest-arrival Connection Scan over the real CDN connection pages, with the standard-library
reader. It is NOT a correct router: no walking, no transfers table, no realtime, no in-seat transfers, and only
the earliest arrival is searched. It exists to measure the cost of the scan itself, and to check the earliest
arrival against the live iRail API.

Run from the repository root:
  uv run python experiments/cdn/planner_spike.py [DIR] [--api]
(--api also asks api.irail.be for the same queries; needs network access to it.)
"""

import argparse
from bisect import bisect_left
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

from _common import data_dir, rss_mb
from pyrail.cdn.arrow import read_table

INF = 10**12
DAY = 24 * 3600


def load(data: Path):
    """Return stops, the manifest's page list for the pages we have, and a loader for one page."""
    manifest = json.loads((data / "manifest.jsonld").read_text())
    stops = read_table((data / "stops.arrow").read_bytes())
    files = sorted((data / "pages").glob("p*.arrow"), key=lambda p: int(p.stem[1:]))
    first = next(i for i, p in enumerate(manifest["connections"]["pages"]) if p["minDepartureTime"][:10] >= "2026-11-12")
    pages = manifest["connections"]["pages"][first : first + len(files)]
    return stops, pages, files


def decode_pages(pages, files, t_from: int, t_to: int):
    """Decode the pages that can hold departures in [t_from, t_to) into one list of connections sorted by departure."""
    connections = []
    decoded = 0
    for meta, path in zip(pages, files, strict=True):
        epoch = meta["epochSeconds"]
        low = datetime.fromisoformat(meta["minDepartureTime"].replace("Z", "+00:00")).timestamp()
        high = datetime.fromisoformat(meta["maxDepartureTime"].replace("Z", "+00:00")).timestamp()
        if high < t_from or low >= t_to:
            continue
        decoded += 1
        t = read_table(path.read_bytes())
        connections.extend(
            zip(
                (epoch + o for o in t["departureTimeOffset"]),
                (epoch + o for o in t["arrivalTimeOffset"]),
                t["departureStopIdx"],
                t["arrivalStopIdx"],
                t["tripIdx"],
                t["serviceDate"],
                t["pickupType"],
                t["dropOffType"],
                strict=True,
            )
        )
    return connections, decoded


def earliest_arrival(connections, deps, min_transfer, n_stops, source, target, t0):
    """Plain Connection Scan: earliest arrival at target when leaving source at or after t0, or INF."""
    arrival = [INF] * n_stops
    arrival[source] = t0
    reached = set()
    best = INF
    for index in range(bisect_left(deps, t0), len(connections)):
        dep, arr, dep_stop, arr_stop, trip, date, pickup, dropoff = connections[index]
        if dep >= best:
            break
        key = (trip, date)
        if key in reached:
            usable = True
        elif pickup == 1:
            usable = False
        else:
            ready = arrival[dep_stop]
            usable = (ready if dep_stop == source else ready + min_transfer[dep_stop]) <= dep
        if usable:
            reached.add(key)
            if dropoff != 1 and arr < arrival[arr_stop]:
                arrival[arr_stop] = arr
                if arr_stop == target:
                    best = arr
    return best


def api_arrival(source_iri: str, target_iri: str, t0: int):
    local = datetime.fromtimestamp(t0, UTC) + timedelta(hours=1)  # Brussels is UTC+1 in November
    number = lambda iri: iri.rsplit("/", 1)[1]  # noqa: E731
    url = (
        f"https://api.irail.be/connections/?from={number(source_iri)}&to={number(target_iri)}"
        f"&date={local:%d%m%y}&time={local:%H%M}&timesel=departure&format=json&results=1"
    )
    data = json.load(urlopen(Request(url, headers={"User-Agent": "pyrail-experiments"}), timeout=30))  # noqa: S310
    return int(data["connection"][0]["arrival"]["time"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dir", nargs="?", default="data")
    parser.add_argument("--api", action="store_true")
    args = parser.parse_args()
    data = data_dir([args.dir])

    stops, pages, files = load(data)
    index = {iri: i for i, iri in enumerate(stops["iri"])}
    arlon = stops["name"].index("Arlon")
    station = lambda number: index[f"http://irail.be/stations/NMBS/{number}"]  # noqa: E731
    queries = [
        ("Brussels-South to Antwerpen-Centraal (short)", station("008814001"), station("008821006")),
        ("Gent-Sint-Pieters to Liege-Guillemins (medium)", station("008892007"), station("008841004")),
        ("Oostende to Arlon (long, transfers)", station("008891702"), arlon),
    ]
    t0 = int(datetime(2026, 11, 12, 7, 0, tzinfo=UTC).timestamp())  # 08:00 Brussels time
    min_transfer = stops["minTransferTime"]

    print(f"rss at start: {rss_mb()} MB; query time {datetime.fromtimestamp(t0, UTC):%Y-%m-%d %H:%MZ}")
    for window_name, window in (("24 h window", DAY), ("48 h window (worst case)", 2 * DAY)):
        start = time.perf_counter()
        connections, decoded = decode_pages(pages, files, t0, t0 + window)
        decode_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        deps = [c[0] for c in connections]  # already sorted: pages and rows are in departure order
        assert deps == sorted(deps)  # noqa: S101
        prep_ms = (time.perf_counter() - start) * 1000
        print(f"\n== {window_name}: {decoded} pages, {len(connections)} connections; decode {decode_ms:.0f} ms, "
              f"list prep {prep_ms:.0f} ms, rss {rss_mb()} MB")
        for label, source, target in queries:
            times = []
            for _ in range(5):
                start = time.perf_counter()
                result = earliest_arrival(connections, deps, min_transfer, len(stops["iri"]), source, target, t0)
                times.append((time.perf_counter() - start) * 1000)
            # six alternatives, proxied by six consecutive searches each starting 10 minutes after the previous
            start = time.perf_counter()
            for k in range(6):
                earliest_arrival(connections, deps, min_transfer, len(stops["iri"]), source, target, t0 + 600 * k)
            six_ms = (time.perf_counter() - start) * 1000
            arrival = datetime.fromtimestamp(result, UTC).strftime("%H:%MZ") if result < INF else "none"
            line = f"   {label}: earliest arrival {arrival}; 1 search {min(times):.0f} ms (best of 5); 6 searches {six_ms:.0f} ms"
            if args.api and window == DAY:
                line += f"; API says {datetime.fromtimestamp(api_arrival(stops['iri'][source], stops['iri'][target], t0), UTC):%H:%MZ}"
            print(line)


main()
