"""How well does the GTFS Realtime snapshot line up with the timetable? (spike #248, input for #253)

Checks, for the trips running today (UTC): how many have a realtime entry, how many entries match a trip in
trips.arrow by the documented template, how many match only without the last field of the trip id, and how many
stop updates carry a platform. Downloads today's connection pages (about 10 MB) with the standard library.

Run from the repository root:
  uv run --group experiments python experiments/cdn/analyze_realtime.py [DIR]
Fetch a fresh snapshot first (fetch_data.py) so the feed and the timetable date from the same day.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime
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

today = datetime.now(UTC).strftime("%Y%m%d")
running = set()
for page in manifest["connections"]["pages"]:
    if page["minDepartureTime"][:10].replace("-", "") != today:
        continue
    request = Request(BASE + page["@id"], headers={"User-Agent": "pyrail-experiments"})  # noqa: S310
    table = read_table(urlopen(request, timeout=60).read())  # noqa: S310
    running.update(trip for trip, date in zip(table["tripIdx"], table["serviceDate"], strict=True) if str(date) == today)

feed = gtfs_realtime_pb2.FeedMessage()
feed.ParseFromString((data / "trip-updates.pb").read_bytes())
updates = [e.trip_update for e in feed.entity if e.HasField("trip_update")]
print(f"today {today}: {len(running)} trips run in the pages; the feed has {len(updates)} trip updates "
      f"({100 * len(updates) / max(1, len(running)):.0f}% of today's trips)")
print("trip schedule_relationship (0 scheduled, 1 added, 3 canceled):", dict(Counter(u.trip.schedule_relationship for u in updates)))

outcome = Counter()
for update in updates:
    trip_id = update.trip.trip_id
    if trip_id in by_id:
        outcome["exact match with the documented template"] += 1
        continue
    candidates = [i for i in by_prefix.get(trip_id.rsplit(":", 1)[0], []) if i in running]
    outcome["no exact match; unique match by id without last field + running today" if len(candidates) == 1
            else f"no exact match; {len(candidates)} candidates running today"] += 1
for label, count in outcome.items():
    print(f"  {count:4}  {label}")
print("last field of the trip ids that do not match exactly:",
      Counter(u.trip.trip_id.rsplit(":", 1)[1] for u in updates if u.trip.trip_id not in by_id).most_common(3))

stops = [s for u in updates for s in u.stop_time_update]
print(f"stop updates: {len(stops)}; with a platform suffix in stop_id: {sum('_' in s.stop_id for s in stops)}; "
      f"skipped stops: {sum(s.schedule_relationship == 1 for s in stops)}")
