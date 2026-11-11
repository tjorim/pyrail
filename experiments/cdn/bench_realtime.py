"""Parse the GTFS Realtime trip-updates snapshot with gtfs-realtime-bindings (protobuf).

Run: uv run --with gtfs-realtime-bindings python bench_realtime.py [DIR]
"""

import time

from google.transit import gtfs_realtime_pb2

from _common import data_dir, rss_mb

raw = (data_dir() / "trip-updates.pb").read_bytes()
start = time.perf_counter()
feed = gtfs_realtime_pb2.FeedMessage()
feed.ParseFromString(raw)
print(f"{len(raw)} bytes, {len(feed.entity)} entities, parsed in {(time.perf_counter() - start) * 1000:.1f} ms, peak RSS {rss_mb()} MB")
update = next(e.trip_update for e in feed.entity if e.HasField("trip_update"))
print("example stop ids:", [s.stop_id for s in update.stop_time_update][:4], "(a _N suffix is the platform)")
