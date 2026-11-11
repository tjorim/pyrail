"""How well does the GTFS Realtime snapshot line up with the timetable? (spike #248, input for #253)

Checks, for the trips running today (UTC): how many have a realtime entry, how many entries match a trip in
trips.arrow by the documented template, how many match only without the last field of the trip id, and how many
stop updates carry a platform. Downloads today's connection pages (about 10 MB) with the standard library.

Run from the repository root:
  uv run --group experiments python experiments/cdn/analyze_realtime.py [DIR]
Fetch a fresh snapshot first (fetch_data.py) so the feed and the timetable date from the same day.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
import json
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

from google.transit import gtfs_realtime_pb2

from _common import data_dir
from pyrail.cdn.arrow import read_table

BASE = "https://irail.github.io"
TEMPLATE = "https://irail.be/id/nmbs-sncb/trips/"
data = data_dir()
manifest = json.loads((data / "manifest.jsonld").read_text())
trips = read_table((data / "trips.arrow").read_bytes())
ids = [unquote(iri[len(TEMPLATE) :]) for iri in trips["iri"]]
by_id = {trip_id: index for index, trip_id in enumerate(ids)}
by_prefix = defaultdict(list)
for index, trip_id in enumerate(ids):
    by_prefix[trip_id.rsplit(":", 1)[0]].append(index)

feed = gtfs_realtime_pb2.FeedMessage()
feed.ParseFromString((data / "trip-updates.pb").read_bytes())
updates = [e.trip_update for e in feed.entity if e.HasField("trip_update")]
dates = sorted({u.trip.start_date for u in updates})

# Pages overlapping the service dates of the updates, with a margin: a service day also holds departures a few
# hours either side of UTC midnight (Brussels midnight is 23:00 UTC in winter). Rows are filtered per service date.
def day(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)


window_start, window_end = day(dates[0]) - timedelta(hours=3), day(dates[-1]) + timedelta(hours=30)
running = defaultdict(set)  # service date -> trips running on it
for page in manifest["connections"]["pages"]:
    low = datetime.fromisoformat(page["minDepartureTime"].replace("Z", "+00:00"))
    high = datetime.fromisoformat(page["maxDepartureTime"].replace("Z", "+00:00"))
    if high < window_start or low >= window_end:
        continue
    request = Request(BASE + page["@id"], headers={"User-Agent": "pyrail-experiments"})  # noqa: S310
    table = read_table(urlopen(request, timeout=60).read())  # noqa: S310
    for trip, date in zip(table["tripIdx"], table["serviceDate"], strict=True):
        running[str(date)].add(trip)

total = sum(len(running[date]) for date in dates)
print(f"service dates in the feed: {dates}; trips running on them in the pages: {total}; trip updates: {len(updates)} "
      f"(update-to-trip ratio {100 * len(updates) / max(1, total):.0f}%)")
print("trip schedule_relationship (0 scheduled, 1 added, 3 canceled):", dict(Counter(u.trip.schedule_relationship for u in updates)))

outcome = Counter()
resolved = {}  # (trip index, service date) -> the trip update that resolved to it
for update in updates:
    trip_id = update.trip.trip_id
    date = update.trip.start_date
    if trip_id in by_id:
        outcome["exact match with the documented template"] += 1
        trip = by_id[trip_id]
    else:
        # candidates must run on THIS update's own start_date
        candidates = [i for i in by_prefix.get(trip_id.rsplit(":", 1)[0], []) if i in running[date]]
        trip = candidates[0] if len(candidates) == 1 else None
        outcome["no exact match; unique match by id without last field + running on the update's start_date" if trip is not None
                else f"no exact match; {len(candidates)} candidates running on the update's start_date"] += 1
    if trip is not None and trip in running[date]:
        resolved[trip, date] = update
for label, count in outcome.items():
    print(f"  {count:4}  {label}")
print("last field of the trip ids that do not match exactly:",
      Counter(u.trip.trip_id.rsplit(":", 1)[1] for u in updates if u.trip.trip_id not in by_id).most_common(3))

with_platform = sum(any("_" in s.stop_id for s in u.stop_time_update) for u in resolved.values())
print(f"{len(resolved)} distinct (trip, service date) pairs among the updates resolve to a trip running that day; "
      f"{with_platform} of them have at least one stop update that names a platform")
print(f"platform coverage: {with_platform} of {total} running trips ({100 * with_platform / max(1, total):.0f}%)")
stops = [s for u in updates for s in u.stop_time_update]
print(f"stop updates: {len(stops)}; with a platform suffix in stop_id: {sum('_' in s.stop_id for s in stops)}; "
      f"skipped stops: {sum(s.schedule_relationship == 1 for s in stops)}")
