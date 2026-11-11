# CDN experiments

Throwaway scripts behind the spike in [#247](https://github.com/tjorim/pyrail/issues/247) (reading the iRail
CDN's Arrow files and GTFS Realtime feed) and the plan in [#246](https://github.com/tjorim/pyrail/issues/246).
They are **not** part of the package: ruff, ty, the test suite and the build all skip this directory.
They exist so the measurements in #247 can be repeated when the CDN data, the libraries or the hardware
change. Re-run them, don't trust the numbers below forever.

## Setup

```bash
python experiments/cdn/fetch_data.py data --date 2026-11-12 --pages 8   # about 20 MB; `data/` is git-ignored
```

Pick a `--date` inside the manifest's coverage. Each script takes the data directory as its last argument
(default `data`). Scripts that import `pyrail` run from the repository root with `uv run`; extra libraries are
added with `uv run --with ...` so nothing is installed into the project.

## Scripts

| Script | Question it answers | Run |
|---|---|---|
| `fetch_data.py` | Downloads the tables, the realtime snapshot and consecutive connection pages. | `python experiments/cdn/fetch_data.py data` |
| `check_schema_message.py` | Do the CDN files start with a Schema message? (No: a record batch.) | `uv run python experiments/cdn/check_schema_message.py data` |
| `probe_nanoarrow.py` | Does nanoarrow read the files? (No, but it reads the same table as an IPC stream.) | `uv run --with nanoarrow python experiments/cdn/probe_nanoarrow.py data` |
| `compare_readers.py` | Does `pyrail.cdn.arrow.read_table` return the same values as pyarrow and arro3? | `uv run --with arro3-io python experiments/cdn/compare_readers.py data` |
| `bench_readers.py` | Time and peak memory of one reader (`stdlib`, `pyarrow` or `arro3`) over all files. | `uv run python experiments/cdn/bench_readers.py stdlib data` |
| `bench_realtime.py` | Cost of parsing the GTFS Realtime snapshot. | `uv run --with gtfs-realtime-bindings python experiments/cdn/bench_realtime.py data` |
| `check_ha_requirements.py` | Does Home Assistant core require any Arrow library? | `python experiments/cdn/check_ha_requirements.py` |
| `pypi_health.py` | Release cadence and wheel platforms of the candidate libraries. | `python experiments/cdn/pypi_health.py` |

## Results (11 November 2026)

Release `nmbs-sncb-20261111-5c05082d`; x86_64 sandbox, 4 cores, 16 GB, Python 3.13. **No Raspberry Pi or other
Home Assistant-class hardware was measured.** The figures are one run each, so treat differences of a few
milliseconds or megabytes as noise.

`bench_readers.py`: 12 files (4 tables, 8 connection pages), 133,153 rows, every column decoded to Python lists
including the `iri` strings. Peak RSS is shown as "start -> end"; the stdlib reader's start is higher because
importing `pyrail` pulls in aiohttp.

| Reader | Time | Peak RSS | Installed size |
|---|---|---|---|
| `pyrail.cdn.arrow.read_table` (stdlib) | 80 ms | 36 -> 90 MB | none |
| pyarrow 26.0.1 | 46 ms | 36 -> 96 MB | 166 MB |
| arro3-io 0.9.1 | 154 ms | 41 -> 71 MB | 34 MB (with arro3-core) |
| nanoarrow 0.9.0 | not possible | | 3 MB |

- All three readers that can open the files return identical values on all 12 files.
- The files contain no Schema message before the record batches (`check_schema_message.py`), which is why
  nanoarrow rejects them: `Unexpected message type at start of input (expected Schema)`. The same table written
  as an IPC stream works.
- Realtime snapshot: about 108 KB, 360 trip entities, parsed in under 1 ms with `gtfs-realtime-bindings`
  (peak RSS 45 MB). Stop ids carry the platform as a suffix (`8896800_1`).
- Memory is similar for all three; speed ranks pyarrow, stdlib, arro3. Neither is large enough to decide the
  choice; the 166 MB installed size and the missing armv7 wheels of pyarrow do.
- The earlier figures in #247 (64 ms and 53 MB for 8 pages) measured pages only and started from a leaner
  process, so they are not comparable with this table.

Library health, from `pypi_health.py` (counts relative to 11 November 2026):

| Library | Releases | Last 12 months | Newest | cp313 wheels |
|---|---|---|---|---|
| pyarrow | 66 since 2017 | 7 | 8 days | Linux x86_64 and aarch64 (glibc, musl), macOS, Windows x64; no armv7 or 32-bit |
| arro3-core | 24 since 2024 | 6 | 29 days | many, including armv7, i686, ppc64le, s390x |
| nanoarrow | 6 since 2024 | 2 | 98 days | many, including win32 and wasm |

Home Assistant core (`check_ha_requirements.py`, `dev` branch): no Arrow library in `requirements_all.txt`,
`package_constraints.txt` or `requirements.txt`; `numpy==2.3.2` and `pandas==2.3.3` (constraint only) are the
nearest. Only direct requirements are visible there, and custom integrations were not checked.

## Not covered

GitHub activity, contributor counts and download numbers (not reachable from the sandbox), Raspberry Pi
measurements, and memory for a realistic route-planning query ([#261](https://github.com/tjorim/pyrail/issues/261)).
