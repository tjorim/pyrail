"""Release cadence, wheel platforms and size of the Arrow-related packages, from PyPI (stdlib only).

Run: python pypi_health.py [package ...]
Release counts are relative to today. GitHub activity, contributors and download counts are not covered.
"""

from datetime import UTC, datetime
import json
import sys
from urllib.request import Request, urlopen

PACKAGES = sys.argv[1:] or ["pyarrow", "nanoarrow", "arro3-core", "arro3-io", "polars"]
now = datetime.now(UTC)

for package in PACKAGES:
    request = Request(f"https://pypi.org/pypi/{package}/json", headers={"User-Agent": "pyrail-experiments"})  # noqa: S310
    data = json.load(urlopen(request, timeout=60))  # noqa: S310
    releases = sorted(
        min(datetime.fromisoformat(f["upload_time_iso_8601"]) for f in files)
        for files in data["releases"].values()
        if files and not any(f.get("yanked") for f in files)
    )
    last_year = sum((now - date).days <= 365 for date in releases)
    wheels = sorted({f["filename"].rsplit("-", 1)[-1][:-4] for f in data["urls"] if "-cp313-cp313-" in f["filename"] or "-abi3-" in f["filename"] or "-py3-none-" in f["filename"]})
    print(f"{package} {data['info']['version']}: {len(releases)} releases since {releases[0].date()}, "
          f"{last_year} in the last 12 months, newest {(now - releases[-1]).days} days ago")
    print("   cp313 wheels:", ", ".join(wheels) or "(none; pure Python or abi3)")
