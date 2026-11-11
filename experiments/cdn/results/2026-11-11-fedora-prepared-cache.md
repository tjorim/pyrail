# Prepared connection-window cache

Measured locally at 2026-11-11T20:19:34.591705+00:00, Python 3.12.13, `Linux-7.2.15-300.fc45.x86_64-x86_64-with-glibc2.44`. Runtime base `357ffcd405db4c9a4e8e3b40b9b02a3cfecd0ff0` plus the accompanying prepared-window and benchmark changes. Release `nmbs-sncb-20261111-5c05082d`; no HTTP requests.

## Results

Each mode/window runs in a fresh subprocess. All modes perform the same raw-file benchmark first. The memory and prepared modes retain sixteen decoded Arrow files. A first window preparation is timed separately and excluded from the three warm lookup/preparation samples. The 24-hour window uses five pages; the 48-hour window uses nine.

| Window | Cache layer | First window preparation ms | Warm median ms | Samples ms | Peak RSS MiB |
|---|---|---|---|---|---|
| 24 h | uncached | 69.069 | 53.170 | [52.97, 53.17, 53.927] | 109 |
| 24 h | memory | 37.846 | 19.712 | [19.687, 19.712, 20.01] | 123 |
| 24 h | prepared | 39.100 | 0.259 | [0.182, 0.268, 0.259] | 122 |
| 48 h | uncached | 97.656 | 87.488 | [83.812, 90.376, 87.488] | 109 |
| 48 h | memory | 57.263 | 35.275 | [38.969, 35.275, 34.066] | 134 |
| 48 h | prepared | 57.560 | 0.443 | [0.333, 3.201, 0.443] | 135 |

Modes: `uncached` reads/decodes pages and prepares rows every time; `memory` reuses decoded Arrow columns but rebuilds, filters and sorts rows and the departure index; `prepared` reuses immutable sorted rows and their index after file-stat/metadata checks.

Prepared-worker counters are one miss and three hits for each window, confirming initial construction followed by reuse. Table digests, prepared-row digests and arrival timestamps are identical across all three modes. Row digests are normalized to tuple representation outside the timed interval. The benchmark excludes stop/manifest setup from window timing, and includes no network, realtime overlay or full production routing.

| Window | Cache layer | Short search samples ms | Long search samples ms |
|---|---|---|---|
| 24 h | uncached | [0.586, 0.584, 0.601] | [2.0, 2.03, 1.97] |
| 24 h | memory | [0.591, 0.568, 0.588] | [2.044, 2.017, 2.005] |
| 24 h | prepared | [0.587, 0.592, 0.598] | [2.018, 2.093, 2.098] |
| 48 h | uncached | [0.606, 0.706, 0.627] | [1.976, 2.387, 2.096] |
| 48 h | memory | [0.599, 0.597, 0.579] | [2.047, 1.995, 1.952] |
| 48 h | prepared | [0.605, 0.645, 0.607] | [2.063, 2.1, 2.091] |

The scan algorithm is unchanged: searches already reuse the prepared rows in every mode. The improvement is avoiding repeated preparation of the same exact window, not speeding up an individual scan or caching its answer.

## Invalidation and lifecycle

- The experiment-only PreparedConnectionCache retains at most two windows by default (LRU) and accepts a separately owned decoded-table cache. Both window rows and the departure index are immutable tuples.
- Keys include release ID, exact [start, end) range, relevant page order/paths, captured metadata and device/inode/size/mtime/ctime signatures. Metadata changes, including an epoch change with identical Arrow bytes, require rebuilding. Callers must supply current release/page metadata after a refresh.
- Missing files and decode errors propagate; an old window is not substituted. A source change during preparation is rejected before the new window is published.
- Hits stat relevant files and serialize metadata, without reading Arrow, reconstructing tuples, filtering or sorting. File signatures are not cryptographic integrity checks. A future realtime overlay must have its own cache version/invalidation rules.
- clear() releases prepared entries but leaves the decoded-table cache alone. Eviction bounds window count, not bytes; caller-held snapshots can keep data alive. Concurrent threads require external synchronization.
- New time ranges/releases and a new process/cache are misses. Canonical windows can be shared across journey queries with different sources/targets. This benchmark retains one prepared window per worker; retaining two overlapping windows can use more memory. RSS includes first construction, all decoded data, verification and search work and is not a standalone cache-size measurement.

## Integration and validation

The planner spike enables prepared caching by default; --no-prepared-cache retains only decoded-table caching, and --no-decoded-cache disables both. Its CLI still calculates multiple journeys from a prepared window; to benefit across repeated preparations, a long-lived caller must reuse the cache instance. Full routing features remain outside the spike.

Eight new standalone tests verify no-read/no-rebuild hits, immutable sorted data, time/release/file/metadata invalidation, missing/corrupt data, source changes during preparation, LRU/clear and invalid inputs. Sixty-eight standalone downloader/benchmark checks and 187 regular non-live tests pass; package coverage is 99.13%. Lint, formatting and types pass. The real-data planner CLI also completes with the cache enabled.

```bash
uv run --locked python experiments/cdn/bench_decoded_cache.py data --write results.json
uv run --locked python experiments/cdn/planner_spike.py data
```

Three warmed samples in fixed order are a small local observation; CPU frequency/scheduling and filesystem cache state affect timings. First-build and metadata-reading costs are separate from a cache hit. No Home Assistant-class hardware result is claimed. Raw evidence: [JSON](2026-11-11-fedora-prepared-cache.json).
