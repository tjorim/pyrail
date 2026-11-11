"""Download a sample of the iRail CDN data for the other scripts in this directory.

Usage: python fetch_data.py [DIR] [--date YYYY-MM-DD] [--pages N]

Writes to DIR (default: ./data, which git ignores):
  manifest.jsonld, stops.arrow, routes.arrow, trips.arrow, transfers.arrow, irail.json,
  trip-updates.pb (the GTFS Realtime snapshot) and pages/p0.arrow ... pN-1.arrow (consecutive connection pages
  from the first page that departs on --date; default: tomorrow, UTC).
ETags and response bodies are cached in DIR/.http-cache; repeat runs revalidate every URL
and reuse cached bytes on HTTP 304. Only the standard library is needed.
"""

import argparse
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

MANIFEST = "https://irail.github.io/iRail-cdn/manifest.jsonld"


def _atomic_write(path: Path, data: bytes) -> None:
    """Publish a complete cache file; interrupted writes must not replace a good file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(data)
            temporary.flush()
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


class Downloader:
    """Persistent, URL-keyed ETag cache. Every fetch revalidates with the origin.

    Bodies live separately from the sample's filenames, which can refer to a different
    release or date on the next run. A digest binds each validator to its exact bytes.
    No stale data is returned on network/server errors.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory / ".http-cache"

    def get(self, url: str) -> bytes:
        key = sha256(url.encode()).hexdigest()
        body_path = self.directory / f"{key}.body"
        metadata_path = self.directory / f"{key}.json"
        cached = None
        etag = None
        try:
            metadata = json.loads(metadata_path.read_text())
            body = body_path.read_bytes()
            if (
                isinstance(metadata, dict)
                and metadata.get("url") == url
                and metadata.get("sha256") == sha256(body).hexdigest()
                and isinstance(metadata.get("etag"), str)
            ):
                cached = body
                etag = metadata["etag"]
        except (FileNotFoundError, ValueError):
            pass  # Missing or damaged cache entries are unconditional downloads.

        headers = {"User-Agent": "pyrail-experiments"}
        if etag is not None:
            headers["If-None-Match"] = etag
        request = Request(url, headers=headers)
        modified = True
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310
                data = response.read()
                new_etag = response.headers.get("ETag")
        except HTTPError as error:
            if error.code != 304 or cached is None:
                raise
            with error:
                data = cached
                new_etag = error.headers.get("ETag", etag)
            modified = False
            if new_etag == etag:
                return data

        # Publish the body before its metadata. A partial update is detected by the
        # digest on the next run and cannot reuse a validator for different bytes.
        if modified:
            _atomic_write(body_path, data)
        _atomic_write(
            metadata_path,
            json.dumps(
                {
                    "url": url,
                    "etag": new_etag,
                    "sha256": sha256(data).hexdigest(),
                }
            ).encode(),
        )
        return data


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
    downloader = Downloader(out)
    raw = downloader.get(MANIFEST)
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
        (out / f"{name}.arrow").write_bytes(downloader.get(urljoin(MANIFEST, manifest[name])))
    (out / "irail.json").write_bytes(downloader.get(urljoin(MANIFEST, manifest["irail:extensions"]["@id"])))
    (out / "trip-updates.pb").write_bytes(downloader.get(manifest["realtime"][0]["@id"]))

    pages = [p for p in manifest["connections"]["pages"] if p["minDepartureTime"][:10] >= args.date]
    if len(pages) < args.pages:
        msg = f"only {len(pages)} pages from {args.date} on; pick an earlier --date"
        raise SystemExit(msg)
    total = 0
    sample = {"releaseId": manifest["releaseId"], "date": args.date, "pages": []}
    for index, page in enumerate(pages[: args.pages]):
        data = downloader.get(urljoin(MANIFEST, page["@id"]))
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
