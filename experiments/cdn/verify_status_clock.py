"""How well does the clock reproduce the live API's `left` and `arrived` flags? (spike #265)

The CDN data has no stop status. The simplest approximation is "left = scheduled departure + delay has passed",
and the same for `arrived`. This script asks the live API for liveboards and vehicles and counts how often that
rule gives the API's answer, and how late the API's flag flips when it disagrees.

Needs the network only. About 15 requests at 0.6 s intervals.

Run from the repository root: python experiments/cdn/verify_status_clock.py
"""

import json
import sys
import time
from urllib.request import Request, urlopen

API = "https://api.irail.be/v1"
STATIONS = ("BE.NMBS.008814001", "BE.NMBS.008821006", "BE.NMBS.008892007")  # Brussels-South, Antwerpen-Centraal, Gent-Sint-Pieters
VEHICLES_PER_STATION = 3


def get(path: str) -> dict:
    time.sleep(0.6)  # stay well under the API's rate limit
    request = Request(f"{API}/{path}", headers={"User-Agent": "pyrail-experiments"})  # noqa: S310
    with urlopen(request, timeout=40) as response:  # noqa: S310
        return json.loads(response.read())


def flag(value) -> bool:
    return value in ("1", 1, True)


def main() -> int:
    counts = {"liveboard left": [0, 0], "vehicle left": [0, 0], "vehicle arrived": [0, 0]}
    disagreements = []

    def record(name: str, predicted: bool, actual: bool, seconds_since_predicted: int, where: str) -> None:
        counts[name][1] += 1
        counts[name][0] += predicted == actual
        if predicted != actual:
            disagreements.append((name, where, seconds_since_predicted, "API says " + str(actual)))

    for station in STATIONS:
        board = get(f"liveboard?id={station}&format=json&arrdep=departure")
        now = int(board["timestamp"])
        departures = board["departures"]["departure"]
        for departure in departures:
            moment = int(departure["time"]) + int(departure["delay"])
            record("liveboard left", moment <= now, flag(departure["left"]), now - moment, station[-4:])
        for departure in departures[:VEHICLES_PER_STATION]:
            vehicle = get(f"vehicle?id={departure['vehicle']}&format=json")
            now = int(vehicle["timestamp"])
            for stop in vehicle["stops"]["stop"]:
                arrival = int(stop["scheduledArrivalTime"]) + int(stop["arrivalDelay"])
                leaving = int(stop["scheduledDepartureTime"]) + int(stop["departureDelay"])
                record("vehicle arrived", arrival <= now, flag(stop["arrived"]), now - arrival, departure["vehicle"])
                record("vehicle left", leaving <= now, flag(stop["left"]), now - leaving, departure["vehicle"])

    for name, (same, total) in counts.items():
        print(f"{name:16} {same:4} / {total:4} equal ({100 * same / max(total, 1):.0f}%)")
    print(f"{len(disagreements)} disagreements; seconds between the predicted moment and now:")
    for line in sorted(disagreements, key=lambda d: d[2])[:20]:
        print("  ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
