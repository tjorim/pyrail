"""Download a sample of the iRail CDN data for the other scripts in this directory.

Usage: python fetch_data.py [DIR] [--date YYYY-MM-DD] [--pages N]

Writes to DIR (default: ./data, which git ignores):
  manifest.jsonld, stops.arrow, routes.arrow, trips.arrow, transfers.arrow, irail.json,
  trip-updates.pb (the GTFS Realtime snapshot) and pages/p0.arrow ... pN-1.arrow (consecutive connection pages
  from the first page that departs on --date; default: tomorrow, UTC).
Only the standard library is needed.
"""

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

MANIFEST = "https://irail.github.io/iRail-cdn/manifest.jsonld"


def get(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "pyrail-experiments"})  # noqa: S310
    with urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dir", nargs="?", default="data", type=Path)
    parser.add_argument("--date", default=(datetime.now(UTC) + timedelta(days=1)).date().isoformat())
    parser.add_argument("--pages", type=int, default=8)
    args = parser.parse_args()

    if args.pages <= 0:
        parser.error("--pages must be positive")

    out: Path = args.dir
    (out / "pages").mkdir(parents=True, exist_ok=True)
    # A partial refresh must not retain metadata claiming that the old sample is complete.
    (out / "sample.json").unlink(missing_ok=True)
    raw = get(MANIFEST)
    (out / "manifest.jsonld").write_bytes(raw)
    manifest = json.loads(raw)
    print(
        "release",
        manifest["releaseId"],
        "coverage",
        manifest["coverageStart"],
        "to",
        manifest["coverageEnd"],
    )

    for name in ("stops", "routes", "trips", "transfers"):
        (out / f"{name}.arrow").write_bytes(get(urljoin(MANIFEST, manifest[name])))
    (out / "irail.json").write_bytes(get(urljoin(MANIFEST, manifest["irail:extensions"]["@id"])))
    (out / "trip-updates.pb").write_bytes(get(manifest["realtime"][0]["@id"]))

    pages = [p for p in manifest["connections"]["pages"] if p["minDepartureTime"][:10] >= args.date]
    if len(pages) < args.pages:
        msg = f"only {len(pages)} pages from {args.date} on; pick an earlier --date"
        raise SystemExit(msg)
    total = 0
    sample = {"releaseId": manifest["releaseId"], "date": args.date, "pages": []}
    for index, page in enumerate(pages[: args.pages]):
        data = get(urljoin(MANIFEST, page["@id"]))
        total += len(data)
        filename = f"p{index}.arrow"
        (out / "pages" / filename).write_bytes(data)
        sample["pages"].append({"file": filename, "metadata": page})
    (out / "sample.json").write_text(json.dumps(sample, indent=2) + "\n")
    for stale in (out / "pages").glob("p*.arrow"):
        if stale.name not in {page["file"] for page in sample["pages"]}:
            stale.unlink()
    print(f"wrote tables, realtime snapshot and {args.pages} pages ({total / 2**20:.1f} MB) to {out}")


if __name__ == "__main__":
    main()
