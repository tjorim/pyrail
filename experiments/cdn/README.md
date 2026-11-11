# CDN experiments

Scripts behind the spike in [#247](https://github.com/tjorim/pyrail/issues/247) (reading the iRail CDN's Arrow
files and GTFS Realtime feed) and the plan in [#246](https://github.com/tjorim/pyrail/issues/246). They are
**not** part of the package: ruff, ty, the test suite and the build all skip this directory.

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
python experiments/cdn/fetch_data.py data --date 2026-11-12 --pages 8    # about 20 MB; `data/` is git-ignored
uv run --group experiments python experiments/cdn/compare_all.py data --write experiments/cdn/results/<date>.md
```

Pick a `--date` inside the manifest's coverage. `compare_all.py` runs every reader in its own process, checks
that the values they return are identical to pyarrow's (it exits with an error if not), and writes a Markdown
report. **Results are dated files in [`results/`](results/): re-run after a new CDN release, a library
release, or on other hardware, and add a new file instead of trusting old numbers.**

## Scripts

| Script | What it does |
|---|---|
| `fetch_data.py` | Downloads the tables, the realtime snapshot and consecutive connection pages. |
| `compare_all.py` | The comparison above: time, peak memory, installed size and correctness for every reader, plus the realtime parse. Uses `bench_readers.py` and `bench_realtime.py`. |
| `bench_readers.py` | One reader over all files, as one JSON line (`stdlib`, `pyarrow`, `arro3` or `nanoarrow`). |
| `bench_realtime.py` | Parses the GTFS Realtime snapshot. |
| `check_schema_message.py` | Shows that the CDN files start with a record batch, not a Schema message. |
| `probe_nanoarrow.py` | Shows nanoarrow failing on the CDN file but reading the same table as an IPC stream. |
| `check_ha_requirements.py` | Does Home Assistant core require any Arrow library? (Direct requirements only.) |
| `pypi_health.py` | Release cadence and wheel platforms of the candidate libraries. |

## What the results say (details in `results/`)

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

GitHub activity, contributor counts and download numbers (not reachable from the sandbox), Raspberry Pi
measurements, and memory for a realistic route-planning query ([#261](https://github.com/tjorim/pyrail/issues/261)).
