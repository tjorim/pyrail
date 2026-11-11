# Bounded decoded Arrow memory cache

Measured locally at 2026-11-11T20:10:05.899479+00:00, Python 3.12.13, `Linux-7.2.15-300.fc45.x86_64-x86_64-with-glibc2.44`. Runtime base `2612a5acebb16641663832e345e14696f9cc9841` plus the accompanying cache and experiment changes. Release `nmbs-sncb-20261111-5c05082d`. Four tables plus twelve connection pages (16 files). No HTTP requests.

## Measurements

Each mode/window uses a fresh subprocess. The first raw table load primes the memory cache and is excluded from warm medians. Three repeated raw loads are timed, with correctness digests checked outside timed sections. The cache capacity is sixteen entries, so this benchmark retains the complete sample. Cache counters confirm sixteen misses during priming and forty-eight hits over the three raw reloads.

| Window | Mode | First raw load ms | Warm raw reload median ms | Window preparation median ms | Peak RSS MiB |
|---|---|---|---|---|---|
| 24 h | uncached | 107.328 | 89.479 | 59.340 | 109 |
| 24 h | memory | 100.273 | 0.524 | 19.195 | 120 |
| 48 h | uncached | 94.356 | 87.576 | 82.218 | 109 |
| 48 h | memory | 100.818 | 0.544 | 33.546 | 138 |

Raw reloads return all sixteen tables. Cache hits perform path/stat checks and return the same immutable mappings and column tuples, without opening or hashing the Arrow files. First loads still read/decode and freeze columns into tuples; the single first-load observations are not evidence of an initial-load speedup.

Window preparation loads the overlapping connection pages, creates absolute-time tuples, filters to the departure window, sorts and builds the departure index. Stop/manifest metadata setup occurs before this timer. Cached Arrow columns eliminate decoding, but the derived connection list is deliberately rebuilt each time. This distinguishes raw-table cache latency from real preparation work.

| Window | Mode | Short search samples ms | Long search samples ms |
|---|---|---|---|
| 24 h | uncached | [0.8, 0.596, 0.583] | [2.869, 2.03, 1.987] |
| 24 h | memory | [0.618, 0.554, 0.557] | [2.367, 1.961, 1.932] |
| 48 h | uncached | [0.566, 0.588, 0.623] | [1.938, 2.049, 1.964] |
| 48 h | memory | [0.686, 0.586, 0.582] | [2.122, 2.026, 1.953] |

Searches reuse the prepared connection list in both modes. The cache does not change the scan algorithm or turn the prototype into a production router. Table digests, prepared-connection digests and first-arrival timestamps match between cached and uncached workers.

## Memory and lifecycle

The cache retains decoded columns, trading memory for CPU and I/O. Process peak RSS includes all raw-table loads, digest verification, cached entries, connection preparation and searches; it is not the standalone cache size. The uncached worker also temporarily loads all sixteen tables for the raw benchmark. Do not attribute the full peak-RSS difference solely to the cache or compare it directly with older differently scoped runs.

`DecodedTableCache(max_entries=16)` is caller-owned and has an LRU entry-count limit, hit/miss counters and `clear()`. There is no module-global cache. Entry count is not a byte budget: one very large file can still consume substantial memory. Callers holding returned snapshots retain their memory even after eviction/clear. Concurrent threads require caller synchronization.

Entries are keyed by resolved path and invalidated by device, inode, size, mtime and ctime. Hits do no content integrity check. Atomic replacement, ordinary in-place edits and missing files are detected; a file changing during the actual read is rejected. Decode/read failures do not return an old table. Shared mappings and column tuples are read-only, preventing callers from mutating cached values.

## Integration and limits

The planner spike now creates one decoded-table cache and reuses it for stop and page loads, including overlapping 24/48-hour windows. Its `--no-decoded-cache` option disables the cache. Existing benchmarks can keep uncached baselines by omitting the optional cache parameter.

This improves repeated Arrow loading in a long-lived process. It does not reduce the filesystem downloader refresh time directly: the downloader does not decode Arrow. New processes must prime their own cache. The benchmark uses warm filesystem caches, one fixed sample, three repetitions and a simplified planner without footpaths, transfers-table handling, realtime or in-seat transfers. No Home Assistant-class hardware result is claimed.

## Validation and reproduction

Seven new cache tests cover immutable/no-read hits, atomic replacement with preserved size/mtime, in-place edits, missing files, malformed updates/recovery, LRU/clear and concurrent modification during reads. The regular non-live suite passes 187 tests with 99.13% total package coverage; sixty standalone downloader/benchmark checks pass. Lint, formatting and type checks pass. The cached planner CLI also completes on the real sample.

```bash
uv run --locked python experiments/cdn/bench_decoded_cache.py data --write results.json
uv run --locked python experiments/cdn/planner_spike.py data
```

Raw per-worker timing/correctness evidence: [JSON](2026-11-11-fedora-decoded-cache.json). Fetch enough pages to cover both requested windows before running. Small timing differences and first-load differences can reflect CPU scheduling/frequency; use within-run comparisons and do not infer a stable API latency ratio.
