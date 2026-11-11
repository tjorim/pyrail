# Avoiding unchanged CDN sample file writes

Measured locally at 2026-11-11T20:03:32.229170+00:00, Python 3.12.13, `Linux-7.2.15-300.fc45.x86_64-x86_64-with-glibc2.44`. Runtime base `7476f7ff777e79cee5abfba10941e644f9dbc970` plus the accompanying file-publication and benchmark changes. Release `nmbs-sncb-20261111-5c05082d`, sampled date 2026-11-12.

## Method and results

Both variants use the same persistent fresh cache, pooling, concurrency four and twelve-page sample. Each has an excluded priming pass and three measured passes. The baseline bypasses byte comparisons and atomically replaces files unconditionally. The optimized path verifies existing bytes and skips replacements when equal.

| Publication policy | Samples (ms) | Median (ms) | File-content writes per pass | Bytes written per pass | HTTP requests |
|---|---|---|---|---|---|
| Always replace | 60.688, 55.453, 54.749 | 55.453 | 20 | 23,881,886 | 0 |
| Compare and skip unchanged | 23.741, 21.995, 21.967 | 21.995 | 0 | 0 | 0 |

The median fell from **55.5 ms to 22.0 ms** (2.52× faster). All warm passes had nineteen fresh cache hits and zero network response bytes. The baseline rewrote twenty files totaling about 22.8 MiB; the optimized passes wrote no file contents.

Counts include output, HTTP-cache and sample-marker content writes through the atomic writer. Renames/unlinks and filesystem metadata activity are not counted as content writes. The optimized path still reads and hashes cache bodies, checks existing output bytes, parses metadata and schedules tasks. The filesystem cache is warm; results on slower storage may differ. This is a bulk cache refresh check, not a full journey benchmark.

## Correctness

- Equality uses the actual existing bytes after a size check. Missing files, changed sizes and same-size corruption cause an atomic replacement. ETags or timestamps alone are not used to decide whether an output is intact.
- An identical 200 body does not replace the cached body, but any changed validator/deadline metadata is still saved. Fresh HTTP hits do not need metadata rewrites.
- sample.json is temporarily renamed to .sample.previous during the refresh. If unchanged, its original inode and modification time are restored by rename after success. Otherwise its new contents are written atomically before publication. Failed refreshes leave the public marker absent, so partial samples are still rejected; subsequent successful retries can restore the hidden marker.
- Tests cover unchanged inode/mtime preservation, missing/changed/same-size-corrupt outputs, identical 200 bodies with updated ETags, marker preservation across an interrupted refresh, and complete repeat-download behavior for both transports.

## Validation and reproduction

Sixty downloader/benchmark checks and the regular 180-test non-live suite pass. Package coverage is 99.08%; lint, formatting and type checks pass. Nine live tests were excluded.

```bash
uv run --locked python experiments/cdn/bench_downloader.py --date 2026-11-12 --pages 12 --concurrency 4 --compare-writes --skip-api --write results.json
```

The initial attempt also requested an API comparison, which returned HTTP 504 before results could be saved. This comparison was rerun with --skip-api; no new API latency claim is made. Three samples in fixed order are a small local observation, not a latency guarantee. No Raspberry Pi-class hardware was measured.

Raw results: [JSON](2026-11-11-fedora-unchanged-files.json). Previous freshness benchmark: [report](2026-11-11-fedora-fresh-downloader.md). Pick a date inside current CDN coverage when rerunning.
