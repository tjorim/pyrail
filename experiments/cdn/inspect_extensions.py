"""List the columns and fill rate of every table the CDN publishes besides the connection pages (spike #248).

Downloads the extension tables named in irail.json (stations, platforms, headsigns, stop/trip/route enrichment)
into DIR/ext and reads them with pyrail.cdn.arrow.read_table, which also shows that the reader handles them.

Run from the repository root: uv run python experiments/cdn/inspect_extensions.py [DIR]
"""

import json
from urllib.request import Request, urlopen

from _common import data_dir
from pyrail.cdn.arrow import read_table

data = data_dir()
extensions = json.loads((data / "irail.json").read_text())["files"]
(data / "ext").mkdir(exist_ok=True)
for key in ("stations", "platforms", "headsigns", "stopEnrichment", "routeEnrichment", "tripEnrichment"):
    path = data / "ext" / f"{key}.arrow"
    if not path.exists():
        request = Request("https://irail.github.io" + extensions[key]["path"], headers={"User-Agent": "pyrail-experiments"})  # noqa: S310
        path.write_bytes(urlopen(request, timeout=120).read())  # noqa: S310
    table = read_table(path.read_bytes())
    rows = len(next(iter(table.values())))
    print(f"\n== {key}: {rows} rows")
    for column, values in table.items():
        sample = [str(v) for v in values[:2000] if v not in (None, "")][:2]
        print(f"   {column:22} filled {sum(v is not None for v in values):6} / {rows}   e.g. {sample}"[:150])
