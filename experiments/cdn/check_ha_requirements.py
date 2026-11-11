"""Look for Arrow-related libraries in Home Assistant core's requirement files (stdlib only).

Run: python experiments/cdn/check_ha_requirements.py
Limits: only direct requirements are listed in these files, so a transitive use is not visible; custom
integrations (HACS) and add-ons are not covered.
"""

import re
from urllib.request import Request, urlopen

BASE = "https://raw.githubusercontent.com/home-assistant/core/dev/"
FILES = ("requirements_all.txt", "homeassistant/package_constraints.txt", "requirements.txt")
PATTERN = re.compile(r"arrow|arro3|polars|duckdb|fastparquet|geoarrow|lonboard|obstore|^numpy|^pandas|^pyrail|gtfs", re.I)

for name in FILES:
    request = Request(BASE + name, headers={"User-Agent": "pyrail-experiments"})  # noqa: S310
    try:
        text = urlopen(request, timeout=60).read().decode()  # noqa: S310
    except OSError as error:  # raw.githubusercontent.com rate limits (HTTP 429) now and then: re-run later
        print(f"== {name}: could not fetch ({error})")
        continue
    hits = [line for line in text.splitlines() if PATTERN.search(line) and "narrow" not in line]
    print(f"== {name} ({len(text.splitlines())} lines)")
    print("\n".join(f"   {line}" for line in hits) or "   (no matches)")
