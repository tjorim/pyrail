# Event-driven snapshot invalidation

Measured locally at 2026-11-11T20:36:10.018407+00:00, Python 3.12.13, `Linux-7.2.15-300.fc45.x86_64-x86_64-with-glibc2.44`. Runtime base `ee570e8191cf11059ee7af8e0ceeaf657e1095b5` plus the accompanying lifecycle/benchmark changes. Release `nmbs-sncb-20261111-5c05082d`. Completed local sample only: no HTTP/download timings.

## Query measurements

Each time window runs in a fresh process. Both query paths use the same immutable timetable/stop values and identical source/target/departure inputs. One initial result miss per path is recorded separately. Warm medians use twenty repeated identical queries. The event-owned path reads the currently published snapshot and does no filesystem validation; the baseline revalidates page metadata/file signatures for every query.

| Window | Query | Per-query validation hit ms | Event-owned hit ms | Speedup | First event result miss ms |
|---|---|---|---|---|---|
| 24 h | short | 0.170070 | 0.005169 | 32.9× | 0.544966 |
| 24 h | long | 0.170195 | 0.004934 | 34.5× | 1.904645 |
| 48 h | short | 0.279827 | 0.005075 | 55.1× | 0.495213 |
| 48 h | long | 0.291103 | 0.005189 | 56.1× | 2.082590 |

The event-owned hits are approximately five microseconds here. All first/cached arrival values match the validation baseline. This is the same earliest-arrival timestamp prototype, not a full itinerary or realtime route. First/different queries still scan the prepared data.

## Costs moved to refresh/publication

| Window | Initial publication ms | Invalidation ms | No-change republication ms | Peak RSS MiB |
|---|---|---|---|---|
| 24 h | 75.694655 | 0.003006 | 1.690212 | 85 |
| 48 h | 115.122027 | 0.003146 | 3.416290 | 107 |

These publication timings are single observations, separate from warm-query medians. Initial publication reads metadata/stops, decodes pages and prepares a window. No-change republication reuses lower cache layers while checking source versions and reloading metadata, then publishes a new generation. HTTP refresh time is excluded. Results are cleared at refresh start; the first query after every publication incurs a miss. The benchmark records that cost too and checks that queries are blocked between begin and publication.

Peak RSS includes the shared decoded/prepared data, both query caches and scans in the worker. It is not isolated lifecycle memory. A no-change refresh deliberately uses a new result version; this is a conservative invalidation boundary rather than an attempt to preserve result hits across refreshes.

## Ownership contract and state transitions

- SnapshotSession owns the decoded/window/result cache layers. begin_refresh invalidates queries before files can change and clears result entries. publish validates a complete sample, stops and metadata before publishing one immutable snapshot reference. Queries are unavailable until publication succeeds.
- Each refresh has a unique ticket. Superseded, completed or missing tickets cannot publish or invalidate a newer state. Generations and result-version tokens change at every successful publication, even when source bytes are unchanged.
- The async refresh wrapper serializes its downloader calls with an asyncio lock, announces invalidation before writes, and handles download errors and cancellation. The explicit begin/publish/fail protocol is available to manual coordinators, who must serialize all writers themselves.
- Read/decode errors, incomplete sample markers, release mismatches and metadata/stops changes during publication fail closed. There is no stale/last-good fallback. Queries also check endpoint and departure-window bounds in memory.
- All writers must notify the lifecycle. Unannounced external edits are intentionally invisible until the next explicit refresh. This is not a filesystem watcher, and the per-query validation path remains the safer default for uncontrolled files. Old snapshots held externally remain immutable; callers must query through the session to observe invalidation.
- Single event-loop ownership is required; concurrent external threads need synchronization around the complete lifecycle. Realtime overlays are not implemented; their values/versions must enter future snapshot publication before claiming a realtime journey cache.

## Integration, tests and reproduction

The CLI has explicit --event-driven mode for exclusively owned completed samples. Default CLI behavior retains per-query validation. Event mode requires all memory-cache layers and labels its timing output. A long-lived caller can use await session.refresh(...) to coordinate real downloader writes; the benchmark uses explicit events over an existing sample so it makes no network requests.

Twelve new lifecycle tests cover startup unavailability, no-filesystem hits and misses, pre-write invalidation, new/no-change generations, failed publication/retry, incomplete/release-mismatched samples, superseded callbacks, missing/completed tickets, metadata changes during build, stop/bounds validation, unannounced edit behavior, owned download success/error/cancellation, and serialized writer operations. Eighty-eight standalone checks and 187 regular non-live tests pass; package coverage is 99.13%. Lint/format/types pass, and the real-data event-mode CLI completes.

```bash
uv run --locked python experiments/cdn/bench_snapshot_lifecycle.py data --write results.json
uv run --locked python experiments/cdn/planner_spike.py data --event-driven
```

Twenty warm samples in fixed order on one x86_64 machine are a local microbenchmark, not a latency guarantee. Clock resolution is not measurement accuracy. No Raspberry Pi-class hardware, network refresh latency, realtime overlay, or complete production routing was measured. Raw evidence: [JSON](2026-11-11-fedora-event-invalidation.json).
