# Repeated earliest-arrival result cache

Measured locally at 2026-11-11T20:25:58.221291+00:00, Python 3.12.13, `Linux-7.2.15-300.fc45.x86_64-x86_64-with-glibc2.44`. Runtime base `260e8ce3dfe9ceab462d0c78d1d8c17f1439d820` plus the accompanying result-cache and benchmark changes. Release `nmbs-sncb-20261111-5c05082d`; no HTTP requests.

## What is cached

This spike returns an earliest-arrival timestamp or the INF unreachable sentinel. Those immutable scalar results are cached; full itinerary objects, arrive-by results, alternatives and realtime overlays are not implemented by this layer. Queries must have identical inputs and the same immutable prepared-window version to hit.

## Timings

Each 24/48-hour window runs in a fresh process. All methods use the same prepared snapshot and transfer-time values. First window preparation and the initial result miss are measured separately, outside the five-hit medians. Direct hits assume the caller already validated the snapshot. Validated hits call PreparedConnectionCache.prepare first, including page file-stat and metadata checks.

| Window | Query | Scan ms | Validate + scan ms | Initial result miss ms | Direct result hit ms | Validate + result hit ms |
|---|---|---|---|---|---|---|
| 24 h | short | 0.505922 | 0.696881 | 0.524407 | 0.005040 | 0.166654 |
| 24 h | long | 1.996196 | 2.299266 | 2.313643 | 0.005189 | 0.217590 |
| 24 h | unreachable | 9.727072 | 9.803326 | 9.128787 | 0.004939 | 0.163478 |
| 48 h | short | 0.517133 | 0.823350 | 0.530148 | 0.005330 | 0.289985 |
| 48 h | long | 2.034729 | 2.363587 | 2.021233 | 0.004969 | 0.283553 |
| 48 h | unreachable | 19.371620 | 19.230104 | 18.412886 | 0.005180 | 0.324601 |

Short: Brussels-South to Antwerpen-Centraal. Long: Oostende to Arlon. Unreachable: an additional stop with no connections. Departures are 08:00 Europe/Brussels on 12 November 2026. Each worker records three initial misses, thirty result hits and three retained entries. All returned arrival values match direct scans. Direct hits are approximately five microseconds here, while version validation remains the dominant part of a checked hit.

| Window | Initial prepared-window build ms | Pages / rows | Peak RSS MiB |
|---|---|---|---|
| 24 h | 79.202 | 5 / 48,440 | 85 |
| 48 h | 119.880 | 9 / 92,103 | 107 |

Peak RSS includes the decoded tables, prepared connections, scans and result entries in that worker. It does not isolate result-cache memory. The cache keys retain small snapshot version tokens, not connection windows; an explicit weak-reference test verifies that evicted/unowned windows can be collected while result entries remain.

## Keys and invalidation

- Caller-owned JourneyResultCache defaults to 128 LRU entries, with counters and clear(). Keys include snapshot version, copied transfer-time values, stop count, source, target, exact departure timestamp and early-stop option. There is no rounding of time or implicit global cache.
- Prepared windows get unique immutable version tokens. A changed file, page epoch/metadata, release or exact time window rebuilds the prepared snapshot, causing result misses. A window rebuilt after eviction also gets a new token, conservatively missing old results even if its rows are equal.
- query() validates current page/window versions before looking up a result. earliest_arrival(window, ...) is the faster primitive for a snapshot already validated by its caller. It does not perform filesystem checks by itself.
- Callers must provide current stop/transfer values and release/page metadata after refreshes. Transfer-time mutation changes the key. Missing files/failed scans propagate; errors are not cached and old results are not substituted.
- Realtime is outside this prototype. A future delay/cancellation overlay must supply an additional result version or explicitly invalidate results when updated. Current benchmark timings must not be presented as a complete realtime itinerary replacement for the original API.
- Different queries/versions and new processes are misses. Reusing results benefits repeated identical queries, not arbitrary new journey requests. Concurrent threads need caller synchronization.

## Integration and validation

The planner CLI enables result reuse when prepared-window caching is enabled; --no-journey-cache disables this layer. Repeated-query output identifies cache use and reports fractional milliseconds, so a cache hit is not labeled as a new scan. Lower caches retain their existing disable flags.

Eight new tests cover no-scan hits, query options/endpoints/times, mutable transfer times, snapshot versions, unreachable caching, lack of window retention, LRU/clear/errors and file/metadata/release/range validation before lookup. Seventy-six standalone checks and 187 regular non-live tests pass, with 99.13% package coverage. Lint, formatting and types pass. The real-data CLI completes with results enabled.

```bash
uv run --locked python experiments/cdn/bench_journey_cache.py data --write results.json
uv run --locked python experiments/cdn/planner_spike.py data
```

Five samples per operation, fixed order, warm filesystem data and no constrained-device hardware. Nanosecond clock resolution does not imply nanosecond measurement accuracy. Small differences reflect scheduling/frequency and sample noise; the comparison is within the same worker. This changes repeated-query work, not scan complexity or downloader refresh latency. Raw evidence: [JSON](2026-11-11-fedora-journey-cache.json).
