"""Download a sample of the iRail CDN data for the other scripts in this directory.

Usage: python fetch_data.py [DIR] [--date YYYY-MM-DD] [--pages N]

Writes to DIR (default: ./data, which git ignores):
  manifest.jsonld, stops.arrow, routes.arrow, trips.arrow, transfers.arrow, irail.json,
  trip-updates.pb (the GTFS Realtime snapshot) and pages/p0.arrow ... pN-1.arrow (consecutive connection pages
  from the first page that departs on --date; default: tomorrow, UTC).
ETags, explicit freshness and response bodies are cached in DIR/.http-cache; fresh entries
need no request, and stale entries are conditionally revalidated. The default transport uses aiohttp (already a pyrail
runtime dependency) with connection pooling and bounded parallel downloads.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, parse_http_list, urlopen

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


def _fresh_until(headers, response_headers, request_time, now):
    """Explicit freshness only; account for upstream age and time spent in transit (RFC 9111)."""
    directives = {}
    for item in parse_http_list(headers.get("cache-control", "")):
        name, _, value = item.partition("=")
        value = value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        directives.setdefault(name.strip().lower(), []).append(value)
    if "no-store" in directives:
        return None
    vary = {name.strip().lower() for name in headers.get("vary", "").split(",") if name.strip()}
    # These request fields are fixed in both transports (Host follows the URL key).
    if "no-cache" in directives or vary - {"accept-encoding", "user-agent", "host"}:
        return now  # Unknown variants must be revalidated.

    def date(value):
        try:
            return parsedate_to_datetime(value).timestamp()
        except (ValueError, TypeError, OverflowError):
            return None

    date_value = date(response_headers.get("Date"))
    lifetime = 0
    if "max-age" in directives:
        values = directives["max-age"]
        if len(values) != 1 or not values[0].isascii() or not values[0].isdigit() or len(values[0]) > 12:
            return now
        lifetime = int(values[0])
    elif "expires" in headers:
        expires = date(headers["expires"])
        if expires is not None:
            lifetime = max(0, expires - (date_value if date_value is not None else now))
    age = response_headers.get("Age", "0")
    if not age.isascii() or not age.isdigit() or len(age) > 12:
        return now
    initial_age = max(0 if date_value is None else now - date_value, int(age) + max(0, now - request_time))
    return now + max(0, lifetime - initial_age)


class _Cache:
    """Persistent, URL-keyed cache with explicit HTTP freshness and ETag revalidation.

    Bodies live separately from the sample's filenames, which can refer to a different
    release or date on the next run. A digest binds each validator to its exact bytes.
    No stale data is returned on network/server errors.
    """

    def __init__(self, directory: Path, revalidate: bool = False) -> None:
        self.directory = directory / ".http-cache"
        self.revalidate = revalidate

    def _cached(self, url: str):
        key = sha256(url.encode()).hexdigest()
        body_path = self.directory / f"{key}.body"
        metadata_path = self.directory / f"{key}.json"
        cached = None
        etag = None
        entry = {}
        try:
            metadata = json.loads(metadata_path.read_text())
            body = body_path.read_bytes()
            if (
                isinstance(metadata, dict)
                and metadata.get("url") == url
                and metadata.get("sha256") == sha256(body).hexdigest()
                and (metadata.get("etag") is None or isinstance(metadata.get("etag"), str))
            ):
                cached = body
                etag = metadata.get("etag")
                entry = metadata
        except (FileNotFoundError, ValueError):
            pass  # Missing or damaged cache entries are unconditional downloads.

        return body_path, metadata_path, cached, etag, entry

    def _fresh(self, entry):
        now = time.time()
        stored = entry.get("stored_at")
        expiry = entry.get("fresh_until")
        return (
            not self.revalidate
            and isinstance(stored, (int, float))
            and isinstance(expiry, (int, float))
            and math.isfinite(stored)
            and math.isfinite(expiry)
            and stored <= now < expiry
        )

    def _store(self, url, body_path, metadata_path, data, new_etag, modified, response_headers, request_time, entry):
        now = time.time()
        stored_headers = entry.get("cache_headers", {}) if not modified else {}
        if not isinstance(stored_headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in stored_headers.items()
        ):
            stored_headers = {}
        headers = dict(stored_headers)
        for key in ("Cache-Control", "Expires", "Vary"):
            if key in response_headers:
                headers[key.lower()] = response_headers[key]
        expiry = _fresh_until(headers, response_headers, request_time, now)
        if expiry is None:
            metadata_path.unlink(missing_ok=True)
            body_path.unlink(missing_ok=True)
            return data
        # Body and validator are bound by a digest, including after interrupted writes.
        if modified:
            _atomic_write(body_path, data)
        _atomic_write(
            metadata_path,
            json.dumps(
                {
                    "url": url,
                    "etag": new_etag,
                    "sha256": sha256(data).hexdigest(),
                    "cache_headers": headers,
                    "stored_at": now,
                    "fresh_until": expiry,
                }
            ).encode(),
        )
        return data


class Downloader(_Cache):
    """Original synchronous urllib transport, retained for comparison."""

    def get(self, url: str) -> bytes:
        body_path, metadata_path, cached, etag, entry = self._cached(url)
        if cached is not None and self._fresh(entry):
            return cached
        headers = {"User-Agent": "pyrail-experiments", "Accept-Encoding": "identity"}
        if etag is not None:
            headers["If-None-Match"] = etag
        request = Request(url, headers=headers)
        modified = True
        request_time = time.time()
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310
                data = response.read()
                new_etag = response.headers.get("ETag")
                response_headers = response.headers
        except HTTPError as error:
            if error.code != 304 or cached is None:
                raise
            with error:
                data = cached
                new_etag = error.headers.get("ETag", etag)
                response_headers = error.headers
            modified = False

        return self._store(
            url, body_path, metadata_path, data, new_etag, modified, response_headers, request_time, entry
        )


class AsyncDownloader(_Cache):
    """Same disk cache, with a caller-owned pooled aiohttp session."""

    def __init__(self, directory: Path, session: aiohttp.ClientSession, revalidate: bool = False) -> None:
        super().__init__(directory, revalidate)
        self.session = session

    async def get(self, url: str) -> bytes:
        body_path, metadata_path, cached, etag, entry = self._cached(url)
        if cached is not None and self._fresh(entry):
            return cached
        headers = {"User-Agent": "pyrail-experiments", "Accept-Encoding": "identity"}
        if etag is not None:
            headers["If-None-Match"] = etag
        request_time = time.time()
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
                return self._store(
                    url, body_path, metadata_path, cached, new_etag, False, response.headers, request_time, entry
                )
            response.raise_for_status()
            data = await response.read()
            return self._store(
                url,
                body_path,
                metadata_path,
                data,
                response.headers.get("ETag"),
                True,
                response.headers,
                request_time,
                entry,
            )


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


def download_sequential(out: Path, date: str, pages: int, revalidate: bool = False):
    """Original urllib transport, retained as a benchmark baseline."""
    prepare(out)
    downloader = Downloader(out, revalidate)
    raw = downloader.get(MANIFEST)
    jobs, sample = plan(out, raw, date, pages)
    for path, url in jobs:
        _atomic_write(path, downloader.get(url))
    finish(out, raw, sample)


async def download_async(out: Path, date: str, pages: int, concurrency: int = 4, trace_configs=None, revalidate=False):
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    prepare(out)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency)
    async with aiohttp.ClientSession(
        connector=connector, timeout=aiohttp.ClientTimeout(total=60), trace_configs=trace_configs
    ) as session:
        downloader = AsyncDownloader(out, session, revalidate)
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
    parser.add_argument("--revalidate", action="store_true", help="revalidate even fresh cache entries")
    parser.add_argument("--transport", choices=("aiohttp", "urllib"), default="aiohttp")
    args = parser.parse_args()
    if args.pages <= 0 or args.concurrency <= 0:
        parser.error("--pages and --concurrency must be positive")
    if args.transport == "urllib":
        download_sequential(args.dir, args.date, args.pages, args.revalidate)
    else:
        asyncio.run(download_async(args.dir, args.date, args.pages, args.concurrency, revalidate=args.revalidate))


if __name__ == "__main__":
    main()
