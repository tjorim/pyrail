"""Download a sample of the iRail CDN data for the other scripts in this directory.

Usage: python fetch_data.py [DIR] [--date YYYY-MM-DD] [--pages N]

Writes to DIR (default: ./data, which git ignores):
  manifest.jsonld, stops.arrow, routes.arrow, trips.arrow, transfers.arrow, irail.json,
  trip-updates.pb (the GTFS Realtime snapshot) and pages/p0.arrow ... pN-1.arrow (consecutive connection pages
  from the first page that departs on --date; default: tomorrow, UTC).
ETags and response bodies are cached in DIR/.http-cache; repeat runs revalidate every URL
and reuse cached bytes on HTTP 304. The default transport uses aiohttp (already a pyrail
runtime dependency) with connection pooling and bounded parallel downloads.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import aiohttp

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


class _Cache:
    """Persistent, URL-keyed ETag cache. Every fetch revalidates with the origin.

    Bodies live separately from the sample's filenames, which can refer to a different
    release or date on the next run. A digest binds each validator to its exact bytes.
    No stale data is returned on network/server errors.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory / ".http-cache"

    def _cached(self, url: str):
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

        return body_path, metadata_path, cached, etag

    def _store(self, url, body_path, metadata_path, data, new_etag, modified):
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


class Downloader(_Cache):
    """Original synchronous urllib transport, retained for comparison."""

    def get(self, url: str) -> bytes:
        body_path, metadata_path, cached, etag = self._cached(url)
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

        return self._store(url, body_path, metadata_path, data, new_etag, modified)


class AsyncDownloader(_Cache):
    """Same disk cache, with a caller-owned pooled aiohttp session."""

    def __init__(self, directory: Path, session: aiohttp.ClientSession) -> None:
        super().__init__(directory)
        self.session = session

    async def get(self, url: str) -> bytes:
        body_path, metadata_path, cached, etag = self._cached(url)
        headers = {"User-Agent": "pyrail-experiments"}
        if etag is not None:
            headers["If-None-Match"] = etag
        async with self.session.get(url, headers=headers) as response:
            if response.status == 304:
                if cached is None:
                    raise aiohttp.ClientResponseError(
                        response.request_info,
                        response.history,
                        status=304,
                        message="304 without a cached body",
                        headers=response.headers,
                    )
                new_etag = response.headers.get("ETag", etag)
                if new_etag == etag:
                    return cached
                return self._store(url, body_path, metadata_path, cached, new_etag, False)
            response.raise_for_status()
            data = await response.read()
            return self._store(url, body_path, metadata_path, data, response.headers.get("ETag"), True)


def prepare(out: Path):
    (out / "pages").mkdir(parents=True, exist_ok=True)
    # A partial refresh must not claim that the old sample is complete.
    (out / "sample.json").unlink(missing_ok=True)


def plan(out: Path, raw: bytes, date: str, count: int):
    manifest = json.loads(raw)
    pages = [p for p in manifest["connections"]["pages"] if p["minDepartureTime"][:10] >= date]
    if len(pages) < count:
        raise ValueError(f"only {len(pages)} pages from {date} on; pick an earlier --date")
    print("release", manifest["releaseId"], "coverage", manifest["coverageStart"], "to", manifest["coverageEnd"])
    jobs = [
        (out / f"{name}.arrow", urljoin(MANIFEST, manifest[name])) for name in ("stops", "routes", "trips", "transfers")
    ]
    jobs += [
        (out / "irail.json", urljoin(MANIFEST, manifest["irail:extensions"]["@id"])),
        (out / "trip-updates.pb", manifest["realtime"][0]["@id"]),
    ]
    sample = {"releaseId": manifest["releaseId"], "date": date, "pages": []}
    for index, page in enumerate(pages[:count]):
        filename = f"p{index}.arrow"
        jobs.append((out / "pages" / filename, urljoin(MANIFEST, page["@id"])))
        sample["pages"].append({"file": filename, "metadata": page})
    return jobs, sample


def finish(out: Path, raw: bytes, sample):
    _atomic_write(out / "manifest.jsonld", raw)
    for stale in (out / "pages").glob("p*.arrow"):
        if stale.name not in {page["file"] for page in sample["pages"]}:
            stale.unlink()
    _atomic_write(out / "sample.json", (json.dumps(sample, indent=2) + "\n").encode())
    print(f"wrote tables, realtime snapshot and {len(sample['pages'])} pages to {out}")


def download_sequential(out: Path, date: str, pages: int):
    """Original urllib transport, retained as a benchmark baseline."""
    prepare(out)
    downloader = Downloader(out)
    raw = downloader.get(MANIFEST)
    jobs, sample = plan(out, raw, date, pages)
    for path, url in jobs:
        _atomic_write(path, downloader.get(url))
    finish(out, raw, sample)


async def download_async(out: Path, date: str, pages: int, concurrency: int = 4, trace_configs=None):
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    prepare(out)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency)
    async with aiohttp.ClientSession(
        connector=connector, timeout=aiohttp.ClientTimeout(total=60), trace_configs=trace_configs
    ) as session:
        downloader = AsyncDownloader(out, session)
        raw = await downloader.get(MANIFEST)
        jobs, sample = plan(out, raw, date, pages)
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch(path, url):
            async with semaphore:
                _atomic_write(path, await downloader.get(url))

        # A failure cancels and joins the other tasks before the session closes.
        # sample.json is published only after all resources succeed.
        async with asyncio.TaskGroup() as group:
            for path, url in jobs:
                group.create_task(fetch(path, url))
        finish(out, raw, sample)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dir", nargs="?", default="data", type=Path)
    parser.add_argument("--date", default=(datetime.now(UTC) + timedelta(days=1)).date().isoformat())
    parser.add_argument("--pages", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--transport", choices=("aiohttp", "urllib"), default="aiohttp")
    args = parser.parse_args()
    if args.pages <= 0 or args.concurrency <= 0:
        parser.error("--pages and --concurrency must be positive")
    if args.transport == "urllib":
        download_sequential(args.dir, args.date, args.pages)
    else:
        asyncio.run(download_async(args.dir, args.date, args.pages, args.concurrency))


if __name__ == "__main__":
    main()
