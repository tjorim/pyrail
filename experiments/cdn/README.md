# CDN experiments

Scripts behind the spike in [#247](https://github.com/tjorim/pyrail/issues/247) (reading the iRail CDN's Arrow
files and GTFS Realtime feed) and the plan in [#246](https://github.com/tjorim/pyrail/issues/246). They are
**not** part of the package: ruff, ty, pytest and the build skip this directory. CI runs the standalone
downloader and benchmark model checks with unittest; these do not need experiment dependencies.

All explored libraries are installed with one command, as the `experiments` dependency group in
`pyproject.toml` (pinned in `uv.lock`; not part of the default groups, so CI and normal development don't
install them):

```bash
uv sync --group experiments        # pyarrow, arro3-io, nanoarrow, gtfs-realtime-bindings (+ protobuf)
```

| Library | Used for |
|---|---|
| `pyarrow` | Reference reader; also in the `test` group, where the unit tests compare the stdlib reader with it. |
| `arro3-io` (+ `arro3-core`) | Candidate reader and first fallback. |
| `nanoarrow` | Candidate reader; cannot open the CDN files (see below). |
| `gtfs-realtime-bindings` (+ `protobuf`) | GTFS Realtime decoding. |
| `pyrail.cdn.arrow` | The standard-library reader in this repo. |

## Run the comparison

```bash
uv run --locked python experiments/cdn/fetch_data.py data --date 2026-11-12 --pages 8    # about 20 MB; `data/` is git-ignored
uv run --group experiments python experiments/cdn/compare_all.py data --write experiments/cdn/results/2026-11-11.md
```

Pick a `--date` inside the manifest's coverage. `compare_all.py` runs every reader in its own process, checks
that the values they return are identical to pyarrow's (it exits with an error if not), and writes a Markdown
report. **Results are dated files in [`results/`](results/): re-run after a new CDN release, a library
release, or on other hardware, and add a new file instead of trusting old numbers.**

## Downloader cache

`fetch_data.py` stores response bodies and ETags under `DIR/.http-cache`, keyed by the full URL.
Fresh entries are reused without an HTTP request, even without an ETag. Explicit `Cache-Control: max-age`
(or `Expires` when max-age is absent) determines freshness, accounting for `Date`, upstream `Age`, and
request time. Stale entries send `If-None-Match` if an ETag exists; otherwise they download unconditionally.
A `304` renews freshness using updated response headers, retaining previous cache policy when omitted;
a `200` replaces the bytes, validator and policy. Old cache entries without freshness metadata revalidate.

`no-cache` forces revalidation and `no-store` removes the HTTP cache entry. Invalid/duplicate max-age or
invalid Age values are treated as stale; there is no heuristic lifetime or offline/stale-on-error fallback.
Unknown `Vary` fields also force revalidation. Both transports use the same fixed User-Agent and
`Accept-Encoding: identity`, so those variants can be reused safely. A backwards clock change forces
revalidation. `--revalidate` bypasses local freshness to force a conditional request for diagnostics.

The default downloader uses one aiohttp session per refresh. After fetching the manifest, it downloads
independent resources concurrently, with **at most four requests in flight** across all hosts. TCP/TLS
connections are reused within the refresh. aiohttp is already a pyrail runtime dependency; the Arrow
reader still has no third-party dependencies. Use `--concurrency 1` for pooled sequential requests,
`--concurrency N` to adjust the bound, or `--transport urllib` for the original sequential transport.
The request timeout is 60 seconds. A failed download cancels the remaining work and leaves `sample.json`
absent; it is published atomically only after all selected files have been written.

Unchanged files are verified by byte comparison and keep their inode and modification time. Missing or
altered output files are repaired atomically, including same-size corruption; a matching ETag alone does
not prove an output file is intact. An identical 200 response can update cache metadata without rewriting
the cached body. Metadata with a renewed deadline still changes and is written.

The previous `sample.json` is temporarily renamed to `.sample.previous` while a refresh is in progress.
After all files succeed, an identical marker is restored by rename; a changed marker is replaced atomically.
A failed refresh leaves only the hidden marker, so consumers still reject an incomplete sample. Successful
retries can reuse that marker. This avoids rewriting marker bytes but still performs directory metadata I/O.

The cache survives restarts and is separate from output filenames such as `pages/p0.arrow`, so changing
the date or release cannot reuse another URL's validator. Missing/corrupt entries trigger a full download;
HTTP/network errors on required requests still fail the run. Removing `DIR/.http-cache` resets the cache. Cached URLs from older
releases remain on disk until removed. Cache bodies duplicate the selected output files on disk.

## Scripts

| Script | What it does |
|---|---|
| `fetch_data.py` | Downloads the tables, realtime snapshot and connection pages, with persistent ETag revalidation. |
| `test_fetch_data.py` | Downloader cache checks against a local HTTP server; no external network. |
| `compare_all.py` | The comparison above: time, peak memory, installed size and correctness for every reader, plus the realtime parse. Uses `bench_readers.py` and `bench_realtime.py`. |
| `bench_readers.py` | One reader over all files, as one JSON line (`stdlib`, `pyarrow`, `arro3` or `nanoarrow`). |
| `bench_realtime.py` | Parses the GTFS Realtime snapshot. |
| `bench_decoded_cache.py` | Isolated-process comparison of uncached, decoded-table and prepared-window reuse. |
| `snapshot_lifecycle.py` | Refresh tickets, single-writer downloader coordination and atomic immutable snapshot publication. |
| `test_snapshot_lifecycle.py` | Event ordering, failures/cancellation, writer serialization and no-filesystem queries. |
| `bench_snapshot_lifecycle.py` | Per-query validation versus owned event-driven queries; publication costs shown separately. |
| `journey_cache.py` | Bounded earliest-arrival result cache with snapshot/query versioning. |
| `test_journey_cache.py` | Result-key, transfer/source invalidation, eviction and snapshot-retention checks. |
| `bench_journey_cache.py` | Direct scan/result hits and version-validated query timings, including first misses. |
| `prepared_cache.py` | Bounded immutable connection-window and departure-index cache for the planner spike. |
| `test_prepared_cache.py` | Window cache reuse, invalidation, immutability and eviction checks. |
| `bench_downloader.py` | Primes an ETag cache, times full warm sample refreshes, and compares them with public iRail API journey requests. |
| `check_schema_message.py` | Shows that the CDN files start with a record batch, not a Schema message. |
| `probe_nanoarrow.py` | Shows nanoarrow failing on the CDN file but reading the same table as an IPC stream. |
| `inspect_extensions.py` | Columns and fill rates of the tables the CDN publishes besides the connection pages (#248). |
| `analyze_realtime.py` | How the realtime snapshot lines up with the timetable: coverage, trip-id matching, platforms (#248, #253). |
| `check_static_gtfs.py` | The official static GTFS behind the CDN: files, version, platform share (#248, #249). |
| `planner_spike.py` | Earliest-arrival Connection Scan over real pages: timing, memory, check against the live API (#261). |
| `planner_benchmark.py` | Isolated 24/48-hour workers: sorting, early stop versus full scan, unreachable target, arrive-by and departure profiles; optional NumPy storage probe. |
| `test_planner_benchmark.py` | Synthetic checks of the benchmark routing model; run separately with unittest (see below). |
| `disturbances_feed.py` | Rebuilds the API's `/disturbances` response from NMBS's RSS feed, with a last-known-status fallback; `--compare` diffs it against the live API (#263). |
| `test_disturbances_feed.py` | Offline checks of the conversion and the fallback; run with unittest like the other `test_*.py`. |
| `decode_alerts.py` | Decodes the official GTFS-RT service-alerts feed (Belgian Mobility) and diffs it with the RSS feed (#264). Needs `gtfs-realtime-bindings`. |
| `test_decode_alerts.py` | Offline checks; the protobuf parts are skipped without `gtfs-realtime-bindings`. |
| `verify_status_clock.py` | How often `left` / `arrived` computed from the clock equals the live API's flags (#265). |
| `check_ha_requirements.py` | Does Home Assistant core require any Arrow library? (Direct requirements only.) |
| `pypi_health.py` | Release cadence and wheel platforms of the candidate libraries. |

## What the results say (details in `results/`)

Findings of the #248, #249 and #261 spikes (field table, realtime versus timetable, data sources, planner timing):
[`results/2026-11-11-spikes.md`](results/2026-11-11-spikes.md).

- Every reader that can open the files returns identical values on all of them.
- The CDN files have no Schema message before the record batches, which is why nanoarrow rejects them
  (`Unexpected message type at start of input (expected Schema)`).
- Memory is comparable; speed ranks pyarrow, stdlib reader, arro3. Install size (pyarrow 164 MB, arro3 33 MB,
  nanoarrow 3 MB, stdlib none) and platform coverage (pyarrow has no armv7 or 32-bit wheels) decide the choice,
  not speed. See the module docstring of `pyrail/cdn/arrow.py` for the decision.

### On a Home Assistant Yellow (Raspberry Pi CM4, aarch64, musl)

Details in [`results/2026-11-11-yellow.md`](results/2026-11-11-yellow.md); measured on a live device with
other containers running. All 12 files (133k rows): stdlib reader 576 ms and 95 MB peak, pyarrow 372 ms and
108 MB (190 MB installed), arro3-io 733 ms and 83 MB. About 5 to 9 times slower than x86, same ranking, same
conclusion. `trips.arrow` alone takes 158 ms, a connection page 16 to 63 ms. Realtime snapshot (77 KB):
about 1 ms with the `upb` protobuf that Home Assistant core ships, about 200 ms with the pure-Python
protobuf that a plain `pip install` gets on musl aarch64.

### Library health, 11 November 2026 (`pypi_health.py`)

| Library | Releases | Last 12 months | Newest | cp313 wheels |
|---|---|---|---|---|
| pyarrow | 66 since 2017 | 7 | 8 days | Linux x86_64 and aarch64 (glibc, musl), macOS, Windows x64; no armv7 or 32-bit |
| arro3-core | 24 since 2024 | 6 | 29 days | many, including armv7, i686, ppc64le, s390x |
| nanoarrow | 6 since 2024 | 2 | 98 days | many, including win32 and wasm |

Home Assistant core (`check_ha_requirements.py`, `dev` branch): no Arrow library in `requirements_all.txt`,
`package_constraints.txt` or `requirements.txt`; `numpy==2.3.2` and `pandas==2.3.3` (constraint only) are the
nearest. Only direct requirements are visible there, and custom integrations were not checked.

## Not covered

Journey planning on Home Assistant-class hardware: the reader and realtime numbers were measured on a Home
Assistant Yellow (see above), but `planner_benchmark.py` was not run there (#261). GitHub activity,
contributor counts and download numbers are also not measured here. The routing benchmark still omits footpaths, the transfers
table, realtime and in-seat transfers; it does not validate a production router.

## Follow-up measurements for #247 and #261

```bash
# Twelve pages cover both complete windows for this release; the benchmark rejects insufficient coverage.
uv run --locked python experiments/cdn/fetch_data.py data --date 2026-11-12 --pages 12
uv run python experiments/cdn/planner_benchmark.py data --write results.json
# Optional probe: NumPy storage with the same Python scan, not a vectorized or compiled algorithm.
uv run --with numpy==2.5.4 python experiments/cdn/planner_benchmark.py data --numpy --write results-numpy.json
uv run python -m unittest discover -s experiments/cdn -p 'test_*.py'
```

Choose a date within current CDN coverage. `fetch_data.py` records the release, date and exact page mapping
in `sample.json`; rerun it for older downloads that lack this file. It removes stale downloaded pages after
a successful refresh. `planner_spike.py --date YYYY-MM-DD` can override its default sampled query date.

Each benchmark window and storage variant runs in a fresh process, so a 48-hour peak cannot leak into a
24-hour result. RSS is the process high-water mark, including decoding, sorting, conversion and searches;
it is not retained heap size. Decode, sorting, conversion and profiles are single samples; individual scans
report best and median of five repetitions. NumPy workers skip arrive-by and profiles and check that their
arrivals match the tuple workers. Run on an idle machine and repeat before treating small differences as
meaningful. There is no network I/O inside timed sections.

The profile baseline scans once for every distinct source departure and removes dominated journeys. It
measures alternatives in the simplified model, rather than treating six arbitrary searches as alternatives.
See [the follow-up assessment](results/2026-11-11-gaps.md), its raw JSON, and the separate reader/GTFS-RT
comparison. These results support a pure Python starting point for individual scans, but do not establish
Home Assistant performance or justify shipping the repeated-scan profile algorithm unchanged.

## Warm ETag downloader versus the API

```bash
uv run --locked python experiments/cdn/bench_downloader.py --date 2026-11-12 --pages 12 --compare-transports --revalidate --concurrency 4 --write results.json
```

This uses `data/downloader-benchmark` by default, separately from the planner's sample. A priming pass is
excluded from three warm refresh measurements per transport; `--compare-transports` measures urllib,
pooled sequential aiohttp, and pooled aiohttp at the selected concurrency. HTTP statuses, connection
creation/reuse (aiohttp), and body bytes are recorded to distinguish
304 cache hits from changed 200 responses. The API comparison uses the public pyrail client, includes model
parsing, primes each journey, and paces calls one second apart. It needs only normal runtime dependencies.
A full sample refresh and one journey request are different workloads; refresh costs should be amortized
across journeys. See [the original local measurements](results/2026-11-11-fedora-downloader.md) and
[the pooled/parallel comparison](results/2026-11-11-fedora-pooled-downloader.md).

## Fresh-cache refresh benchmark

```bash
uv run --locked python experiments/cdn/bench_downloader.py --date 2026-11-12 --pages 12 --concurrency 4 --compare-freshness --write results.json
```

`--compare-freshness` compares forced ETag revalidation with freshness-aware reuse on the same primed
cache. The report includes local fresh-hit counts as well as actual HTTP statuses and transferred bytes.
Expiry is per URL: for example, the realtime feed can revalidate while timetable files remain fresh.
See [the local freshness results](results/2026-11-11-fedora-fresh-downloader.md). Existing timestamped reports
describe the behavior at the time they were measured.

## Avoiding unchanged file writes

```bash
uv run --locked python experiments/cdn/bench_downloader.py --date 2026-11-12 --pages 12 --concurrency 4 --compare-writes --skip-api --write results.json
```

This compares unconditional atomic replacement with byte-checked publication, on the same fresh HTTP
cache. File-write counts include output files, HTTP cache files and sample-marker contents; renames and
unlinks are not counted as body writes. See [the local results](results/2026-11-11-fedora-unchanged-files.md).

## Decoded Arrow memory cache

`pyrail.cdn.cache.DecodedTableCache` is an explicitly owned, bounded LRU cache:

```python
from pyrail.cdn.cache import DecodedTableCache

cache = DecodedTableCache(max_entries=16)
stops = cache.read("data/stops.arrow")  # read-only mapping, immutable column tuples
same_stops = cache.read("data/stops.arrow")  # stat check; no Arrow read/decode
cache.clear()  # releases the cache's references; callers may still hold snapshots
```

Keep the same cache object alive across queries. A new process/cache must decode its first loads.
Entries invalidate when device/inode, size, mtime or ctime changes; atomic downloader replacements are
therefore visible even when size and mtime match. Unchanged-file publication preserves cache hits.
Missing files and decode errors propagate rather than serving an older snapshot. File metadata checks
are not a cryptographic integrity check. The cache is bounded by entry count, not bytes, and use from
concurrent threads requires external synchronization. Cache hits/misses are exposed for measurement.

The planner spike now owns a cache by default and shares it between stop/page loads; use
`planner_spike.py --no-decoded-cache` to disable it. `load` and `decode_pages` also accept an optional
caller-owned cache. The existing planner benchmark keeps its uncached baseline by default.

```bash
uv run --locked python experiments/cdn/bench_decoded_cache.py data --write results.json
```

The new benchmark uses a fresh process per mode/window, verifies equal table/connection digests and
arrival results, and reports both raw table reloads and complete connection-list preparation. Decoded-table
caching alone does not retain derived connection lists; the prepared-window mode below adds that layer. Neither speeds up
`fetch_data.py` directly: that downloader copies Arrow files without decoding them. Retaining decoded
columns trades resident memory for CPU and file I/O savings. See [the local results](results/2026-11-11-fedora-decoded-cache.md).

## Prepared connection windows

The experiment-only `PreparedConnectionCache` retains a sorted, immutable tuple of connection rows and
its departure-time index for each window. It owns at most two windows by default and shares the caller's
`DecodedTableCache` when provided. Keep the same object alive across journey queries:

```python
from prepared_cache import PreparedConnectionCache

windows = PreparedConnectionCache(max_windows=2, decoded_cache=cache)
window = windows.prepare(pages, files, start, end, release_id=release_id)
# Pass window.connections and window.departures to the spike's scan functions.
windows.clear()  # releases prepared entries; clear the decoded cache separately if desired
```

This snippet runs with `experiments/cdn` on the import path, like the scripts in this directory; it is not
a new public routing API. Keys include the exact time range, release ID, relevant resolved file paths and
metadata snapshots, and file identity/size/mtime/ctime. Changes trigger a rebuild. Metadata includes the
page epoch, which changes absolute connection timestamps even if Arrow bytes remain the same. A hit
stats relevant files and compares metadata; it does not read/decode Arrow or reconstruct/sort rows.
Callers must supply current release/page metadata after refreshes. Realtime is outside this prototype;
a future overlay must have its own version/invalidation rules.

The planner CLI enables both memory caches by default. `--no-prepared-cache` keeps decoded-table caching
but rebuilds windows; `--no-decoded-cache` disables both. Different exact ranges/releases are misses; the
first preparation still does the full work. These are entry-count limits, not memory budgets; callers holding
snapshots can retain them after eviction. Concurrent threads require external synchronization.

The decoded-cache benchmark now includes `prepared` workers and times initial window construction
separately from repeated lookups. It verifies identical row digests and arrivals in all three modes:

```bash
uv run --locked python experiments/cdn/bench_decoded_cache.py data --write results.json
```

See [the prepared-window measurements](results/2026-11-11-fedora-prepared-cache.md). This optimization
avoids repeated preparation of the same window; it does not change scan complexity, implement missing
routing features, or reduce the filesystem downloader's refresh time.

## Repeated earliest-arrival results

`JourneyResultCache` is experiment-only: it caches the immutable earliest-arrival timestamps returned by
this prototype, including unreachable results. It does not cache full itineraries, arrive-by searches or
profiles. It defaults to 128 LRU entries and is explicitly owned by a long-lived caller:

```python
from journey_cache import JourneyResultCache

journeys = JourneyResultCache(max_results=128)
arrival = journeys.query(windows, pages, files, start, end,
                         release_id=release_id, min_transfer=transfer_times,
                         n_stops=n_stops, source=source, target=target, departure=departure)
```

`query` validates the prepared window against current page versions before reusing a result. Keys include
a unique immutable snapshot version, a tuple copy of minimum transfer times, stop count, endpoints,
exact departure time and scan options. Changed versions/inputs require a scan. Keys retain the small version
token rather than the prepared window, so result entries cannot pin evicted connection arrays in memory.
There is no rounding of departure times and no module-global cache. Calls with different inputs are misses.

For a snapshot already validated by the caller, `earliest_arrival(window, ...)` skips repeated file checks.
It must not be used as a replacement for version validation after refreshes. Callers must reload current
stop/transfer data and pass current release/page metadata; mutable transfer-time changes are captured in
the key. Realtime is not implemented by the spike: adding delays/cancellations/other dynamic inputs must
also add their versions to the result key or clear the result cache when they change. No stale-on-error
fallback is provided, and failed scans are not cached. Concurrent threads require external synchronization.

The planner CLI enables this layer with prepared caching; `--no-journey-cache` disables only result reuse.
Its repeated-query output identifies whether the result cache is enabled. Both lower cache layers can be
disabled with their existing flags. New processes and first/different queries still pay scan/preparation costs.

```bash
uv run --locked python experiments/cdn/bench_journey_cache.py data --write results.json
```

The benchmark shows direct result hits separately from complete version-validated lookups, and records
first misses and prepared-window construction separately. Cached/baseline arrivals must agree. See
[the local results](results/2026-11-11-fedora-journey-cache.md).

## Event-driven invalidation (explicit ownership)

`SnapshotSession` owns the decoded, prepared and result caches and binds stops/transfer times to an immutable
published window. Queries use that snapshot without any file reads, stats or page metadata serialization.
Use this only when **every write is coordinated by the session**:

```python
from snapshot_lifecycle import SnapshotSession

session = SnapshotSession()
await session.refresh(data, date, page_count, start, end, concurrency=4)
arrival = session.query(source, target, departure)
```

`refresh` serializes downloader writes, invalidates queries/results before touching files, then validates the
completed sample and publishes one new snapshot reference. Missing/inconsistent sample metadata, read/
decode errors, failed downloads and cancellation leave queries unavailable; callers can retry after a successful
refresh. No last-good/stale fallback is used. Source/target and departure-window bounds are checked in memory.

For an already completed local sample or an external coordinator, use the explicit event protocol:

```python
ticket = session.begin_refresh()  # before any file writes: queries now fail closed
try:
    # Write a complete sample, serialized against every other writer.
    snapshot = session.publish(ticket, data, start, end)
except BaseException:
    session.fail_refresh(ticket)
    raise
```

Tickets prevent superseded/completed callbacks from publishing or clearing newer state. Each publication gets
a new generation/result version, including no-change refreshes; result entries are cleared at refresh start.
Prepared/decoded caches stay bounded and can reuse unchanged files during publication. Metadata/stops are
checked before and after preparing the candidate; all fields are published together after validation. Manual
coordinators must serialize writers; the supplied async `refresh` wrapper does this for its own calls.

This is an event protocol, **not a filesystem watcher**. Unannounced edits remain invisible to queries until
an explicit refresh event. Use the per-query-validation path when writers are not controlled. One event-loop
owner is required; external threads need synchronization around the whole lifecycle. Retained old snapshots
are immutable but are not a substitute for querying through the session. Future realtime overlays must be
included in publication/invalidation before claiming complete realtime journey results.

The planner CLI offers explicit `--event-driven` mode for a completed, exclusively owned sample. It publishes
once per window and labels event mode in output. Default CLI behavior continues validating per query. Cache
bypass flags cannot be combined with event mode.

```bash
uv run --locked python experiments/cdn/planner_spike.py data --event-driven
uv run --locked python experiments/cdn/bench_snapshot_lifecycle.py data --write results.json
```

The benchmark uses completed local samples (no HTTP), separately reports initial publication, invalidation,
no-change republication and first result misses, and compares warm event-owned queries with per-query
validation. See [the local event-lifecycle results](results/2026-11-11-fedora-event-invalidation.md).
