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
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from _common import data_dir, rss_mb
from journey_cache import JourneyResultCache
from prepared_cache import PreparedConnectionCache
from pyrail.cdn.arrow import read_table
from pyrail.cdn.cache import DecodedTableCache

INF = 10**12
DAY = 24 * 3600


def load(data: Path, cache=None):
    """Return stops, the exact sampled page metadata, and matching local files."""
    manifest = json.loads((data / "manifest.jsonld").read_text())
    stops_path = data / "stops.arrow"
    stops = cache.read(stops_path) if cache is not None else read_table(stops_path.read_bytes())
    sample_path = data / "sample.json"
    if not sample_path.exists():
        raise ValueError("missing sample.json: re-run fetch_data.py to record the exact downloaded pages")
    sample = json.loads(sample_path.read_text())
    if sample["releaseId"] != manifest["releaseId"]:
        raise ValueError("sample.json and manifest.jsonld refer to different releases")
    pages = [page["metadata"] for page in sample["pages"]]
    files = [data / "pages" / page["file"] for page in sample["pages"]]
    return stops, pages, files


def decode_pages(pages, files, t_from: int, t_to: int, cache=None):
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
        t = cache.read(path) if cache is not None else read_table(path.read_bytes())
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
    return [c for c in connections if t_from <= c[0] < t_to], decoded


def earliest_arrival(connections, deps, min_transfer, n_stops, source, target, t0, *, early_stop=True):
    """Plain Connection Scan: earliest arrival at target when leaving source at or after t0, or INF."""
    arrival = [INF] * n_stops
    arrival[source] = t0
    reached = set()
    best = INF
    for index in range(bisect_left(deps, t0), len(connections)):
        dep, arr, dep_stop, arr_stop, trip, date, pickup, dropoff = connections[index]
        if early_stop and dep >= best:
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
    local = datetime.fromtimestamp(t0, ZoneInfo("Europe/Brussels"))
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
    parser.add_argument("--no-journey-cache", action="store_true", help="scan on every repeated journey query")
    parser.add_argument("--no-prepared-cache", action="store_true", help="rebuild connection windows on each load")
    parser.add_argument("--no-decoded-cache", action="store_true", help="decode Arrow files on every load")
    parser.add_argument("--date", help="query date; defaults to the sampled date")
    args = parser.parse_args()
    data = data_dir([args.dir])

    cache = None if args.no_decoded_cache else DecodedTableCache()
    prepared_cache = (
        None if args.no_prepared_cache or args.no_decoded_cache else PreparedConnectionCache(decoded_cache=cache)
    )
    journeys = JourneyResultCache() if prepared_cache is not None and not args.no_journey_cache else None
    stops, pages, files = load(data, cache)
    index = {iri: i for i, iri in enumerate(stops["iri"])}
    arlon = stops["name"].index("Arlon")
    station = lambda number: index[f"http://irail.be/stations/NMBS/{number}"]  # noqa: E731
    queries = [
        (
            "Brussels-South to Antwerpen-Centraal (short)",
            station("008814001"),
            station("008821006"),
        ),
        (
            "Gent-Sint-Pieters to Liege-Guillemins (medium)",
            station("008892007"),
            station("008841004"),
        ),
        ("Oostende to Arlon (long, transfers)", station("008891702"), arlon),
    ]
    sample = json.loads((data / "sample.json").read_text())
    date = args.date or sample["date"]
    t0 = int(datetime.fromisoformat(f"{date}T08:00:00").replace(tzinfo=ZoneInfo("Europe/Brussels")).timestamp())
    min_transfer = stops["minTransferTime"]

    print(f"rss at start: {rss_mb()} MB; query time {datetime.fromtimestamp(t0, UTC):%Y-%m-%d %H:%MZ}")
    for window_name, window in (
        ("24 h window", DAY),
        ("48 h window (worst case)", 2 * DAY),
    ):
        start = time.perf_counter()
        if prepared_cache is not None:
            prepared = prepared_cache.prepare(pages, files, t0, t0 + window, release_id=sample["releaseId"])
            connections, deps, decoded = prepared.connections, prepared.departures, prepared.pages
        else:
            connections, decoded = decode_pages(pages, files, t0, t0 + window, cache)
            connections.sort(key=lambda c: c[0])
            deps = [c[0] for c in connections]
        preparation_ms = (time.perf_counter() - start) * 1000
        print(
            f"\n== {window_name}: {decoded} pages, {len(connections)} connections; "
            f"load/prepare {preparation_ms:.0f} ms, rss {rss_mb()} MB"
        )

        def search(source, target, departure):
            if journeys is not None:
                return journeys.query(
                    prepared_cache,
                    pages,
                    files,
                    t0,
                    t0 + window,
                    release_id=sample["releaseId"],
                    min_transfer=min_transfer,
                    n_stops=len(stops["iri"]),
                    source=source,
                    target=target,
                    departure=departure,
                )
            return earliest_arrival(connections, deps, min_transfer, len(stops["iri"]), source, target, departure)

        for label, source, target in queries:
            times = []
            for _ in range(5):
                start = time.perf_counter()
                result = search(source, target, t0)
                times.append((time.perf_counter() - start) * 1000)
            # Six independent searches, not a departure profile; planner_benchmark.py measures actual profiles.
            start = time.perf_counter()
            for k in range(6):
                search(source, target, t0 + 600 * k)
            six_ms = (time.perf_counter() - start) * 1000
            arrival = datetime.fromtimestamp(result, UTC).strftime("%H:%MZ") if result < INF else "none"
            line = (
                f"   {label}: earliest arrival {arrival}; 1 query {min(times):.3f} ms (best of 5; "
                f"result cache {'on' if journeys is not None else 'off'}); 6 queries {six_ms:.3f} ms"
            )
            if args.api and window == DAY:
                line += f"; API says {datetime.fromtimestamp(api_arrival(stops['iri'][source], stops['iri'][target], t0), UTC):%H:%MZ}"
            print(line)


if __name__ == "__main__":
    main()
