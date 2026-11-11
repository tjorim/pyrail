"""Look at the official NMBS/SNCB static GTFS that the CDN is built from (spike #248 and #249).

Downloads the feed from the Belgian Mobility open-data endpoint (about 19 MB, no key was needed on 11 Nov 2026)
into DIR/gtfs and reports its files, its version and validity, and how many stop_times rows name a platform.
Compare feed_info with `feed` in irail.json: they can differ from the version the CDN was built from.

Run: python experiments/cdn/check_static_gtfs.py [DIR]
"""

import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen
import zipfile

URL = "https://api-management-discovery-production.azure-api.net/api/gtfs/feed/nmbssncb/static"
data = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
target = data / "gtfs" / "static.zip"
target.parent.mkdir(parents=True, exist_ok=True)
if not target.exists():
    target.write_bytes(urlopen(Request(URL, headers={"User-Agent": "pyrail-experiments"}), timeout=300).read())  # noqa: S310
archive = zipfile.ZipFile(target)
print({info.filename: info.file_size for info in archive.infolist()})
print("feed_info.txt:", archive.read("feed_info.txt").decode().strip().splitlines()[1].strip())
if (data / "irail.json").exists():
    feed = next(s["feed"] for s in json.loads((data / "irail.json").read_text())["sources"] if s["id"] == "gtfs-static")
    print("CDN built from: version", feed["version"], "valid", feed["startDate"], "to", feed["endDate"])
with archive.open("stop_times.txt") as file:
    header = file.readline().decode().strip().split(",")
    column = header.index("stop_id")
    total = platform = 0
    for line in file:
        total += 1
        platform += "_" in line.decode().split(",")[column]
print(f"stop_times rows: {total}; stop_id names a platform: {platform} ({100 * platform / total:.0f}%)")
print("stop_time_overrides.txt in the feed:", "stop_time_overrides.txt" in archive.namelist())
