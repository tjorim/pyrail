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
uv run --group experiments python experiments/cdn/compare_all.py data --write experiments/cdn/results/<date>.md
```

Pick a `--date` inside the manifest's coverage. `compare_all.py` runs every reader in its own process, checks
that the values they return are identical to pyarrow's (it exits with an error if not), and writes a Markdown
report. **Results are dated files in [`results/`](results/): re-run after a new CDN release, a library
release, or on other hardware, and add a new file instead of trusting old numbers.**

## Downloader cache

`fetch_data.py` stores response bodies and ETags under `DIR/.http-cache`, keyed by the full URL.
Every run contacts the server, sending `If-None-Match` when a matching cached body exists. A `304`
reuses those bytes; a `200` replaces them and its validator. Responses without ETags are downloaded
unconditionally next time. This implements revalidation, not `Cache-Control` freshness or offline fallback.

The default downloader uses one aiohttp session per refresh. After fetching the manifest, it downloads
independent resources concurrently, with **at most four requests in flight** across all hosts. TCP/TLS
connections are reused within the refresh. aiohttp is already a pyrail runtime dependency; the Arrow
reader still has no third-party dependencies. Use `--concurrency 1` for pooled sequential requests,
`--concurrency N` to adjust the bound, or `--transport urllib` for the original sequential transport.
The request timeout is 60 seconds. A failed download cancels the remaining work and leaves `sample.json`
absent; it is published atomically only after all selected files have been written.

The cache survives restarts and is separate from output filenames such as `pages/p0.arrow`, so changing
the date or release cannot reuse another URL's validator. Missing/corrupt entries trigger a full download;
HTTP/network errors still fail the run. Removing `DIR/.http-cache` resets the cache. Cached URLs from older
releases remain on disk until removed. Cache bodies duplicate the selected output files on disk.

## Scripts

| Script | What it does |
|---|---|
| `fetch_data.py` | Downloads the tables, realtime snapshot and connection pages, with persistent ETag revalidation. |
| `test_fetch_data.py` | Downloader cache checks against a local HTTP server; no external network. |
| `compare_all.py` | The comparison above: time, peak memory, installed size and correctness for every reader, plus the realtime parse. Uses `bench_readers.py` and `bench_realtime.py`. |
| `bench_readers.py` | One reader over all files, as one JSON line (`stdlib`, `pyarrow`, `arro3` or `nanoarrow`). |
| `bench_realtime.py` | Parses the GTFS Realtime snapshot. |
| `bench_downloader.py` | Primes an ETag cache, times full warm sample refreshes, and compares them with public iRail API journey requests. |
| `check_schema_message.py` | Shows that the CDN files start with a record batch, not a Schema message. |
| `probe_nanoarrow.py` | Shows nanoarrow failing on the CDN file but reading the same table as an IPC stream. |
| `inspect_extensions.py` | Columns and fill rates of the tables the CDN publishes besides the connection pages (#248). |
| `analyze_realtime.py` | How the realtime snapshot lines up with the timetable: coverage, trip-id matching, platforms (#248, #253). |
| `check_static_gtfs.py` | The official static GTFS behind the CDN: files, version, platform share (#248, #249). |
| `planner_spike.py` | Earliest-arrival Connection Scan over real pages: timing, memory, check against the live API (#261). |
| `planner_benchmark.py` | Isolated 24/48-hour workers: sorting, early stop versus full scan, unreachable target, arrive-by and departure profiles; optional NumPy storage probe. |
| `test_planner_benchmark.py` | Synthetic checks of the benchmark routing model; run separately with unittest (see below). |
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

Raspberry Pi / Home Assistant-class measurements: no suitable hardware is currently available. This is
an explicit validation gap, not an inference from x86 results. GitHub activity, contributor counts and
download numbers are also not measured here. The routing benchmark still omits footpaths, the transfers
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
uv run --locked python experiments/cdn/bench_downloader.py --date 2026-11-12 --pages 12 --compare-transports --concurrency 4 --write results.json
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
