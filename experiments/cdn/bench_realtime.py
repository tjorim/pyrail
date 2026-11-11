"""Parse the GTFS Realtime trip-updates snapshot with gtfs-realtime-bindings (protobuf) and print one JSON line.

Run: uv run --group experiments python experiments/cdn/bench_realtime.py [DIR]
"""

import json
import time

from google.transit import gtfs_realtime_pb2

from _common import data_dir, installed_mb, rss_mb

raw = (data_dir() / "trip-updates.pb").read_bytes()
timings = []
for _ in range(5):
    start = time.perf_counter()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(raw)
    timings.append((time.perf_counter() - start) * 1000)
update = next((e.trip_update for e in feed.entity if e.HasField("trip_update") and e.trip_update.stop_time_update), None)
print(
    json.dumps(
        {
            "bytes": len(raw),
            "entities": len(feed.entity),
            "ms_best": round(min(timings), 2),
            "rss_peak_mb": rss_mb(),
            "installed_mb": round(installed_mb("gtfs-realtime-bindings", "protobuf"), 1),
            "example_stop_ids": [s.stop_id for s in update.stop_time_update][:4] if update else [],
        }
    )
)
