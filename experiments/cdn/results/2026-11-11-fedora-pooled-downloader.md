# Connection pooling and bounded parallel CDN refresh

Measured locally at 2026-11-11T19:06:48.491614+00:00, Python 3.12.13, `Linux-7.2.15-300.fc45.x86_64-x86_64-with-glibc2.44`. Runtime base `dfae4433c8edd202928f83bfba0529dea0f6f31b` plus the accompanying downloader/benchmark changes. Release `nmbs-sncb-20261111-5c05082d`, query/sample date 2026-11-12.

## Method

The same on-disk ETag cache and twelve-page sample were used for all variants: manifest, four core tables, extensions, realtime and twelve connection pages, 19 HTTP requests total. Each variant had an excluded priming run followed by three warm runs. The retained urllib transport uses the same cache/output publication code as the new transport; it preserves the old sequential request behavior. aiohttp creates a fresh session for each refresh and reuses connections within that refresh. Concurrency includes the entire fetch/write operation; the global bound is four simultaneous downloads, including both hosts.

| Transport | Concurrent downloads | Warm samples (ms) | Median (ms) | Speedup vs urllib |
|---|---|---|---|---|
| urllib | 1 | 1612.6, 1801.142, 1679.031 | 1679.0 | 1.00× |
| aiohttp | 1 | 1355.982, 837.644, 801.245 | 837.6 | 2.00× |
| aiohttp | 4 | 319.722, 334.081, 350.934 | 334.1 | 5.03× |

## HTTP/cache evidence

| Variant / warm run | HTTP responses | Response body bytes | Connections created / reused |
|---|---|---|---|
| urllib-1 / 1 | {'304': 19} | 0 | not traced (urllib) |
| urllib-1 / 2 | {'304': 19} | 0 | not traced (urllib) |
| urllib-1 / 3 | {'304': 19} | 0 | not traced (urllib) |
| aiohttp-1 / 1 | {'304': 18, '200': 1} | 103,460 | 2 / 17 |
| aiohttp-1 / 2 | {'304': 19} | 0 | 2 / 17 |
| aiohttp-1 / 3 | {'304': 19} | 0 | 2 / 17 |
| aiohttp-4 / 1 | {'304': 19} | 0 | 5 / 14 |
| aiohttp-4 / 2 | {'304': 19} | 0 | 5 / 14 |
| aiohttp-4 / 3 | {'304': 19} | 0 | 5 / 14 |

Every warm request sent If-None-Match. All parallel-run responses were 304. One pooled sequential run received a changed realtime feed (200); that is normal cache revalidation behavior and its transfer is included in the reported timing. The other two sequential pooled samples had only 304 responses. Cumulative created connections can exceed the concurrency bound as connections to different hosts are opened/replaced; the bound limits simultaneous operations, not lifetime connection creation.

## Compared with the original API

Fresh API measurements with the public IRail client: median 44.1 ms for Brussels-South–Antwerpen-Centraal, 41.6 ms for Oostende–Arlon. These include HTTP, JSON and model parsing, use a shared session, and exclude one priming request per journey and one-second request pacing. API responses were 200 without ETags and returned six/seven alternatives.

Pooling and concurrency materially reduce bulk refresh latency. A full 19-resource refresh is still a different workload from one API journey request: it serves many future searches, and excludes Arrow decoding and routing. Refresh the CDN sample independently and retain decoded data across journeys. These results do not establish that a complete CDN journey implementation is faster than the original API.

## Implementation and checks

- Default: aiohttp session with a connector limit and semaphore bound of four. Use `--concurrency 1` for pooled sequential downloads or `--transport urllib` for the old transport.
- ETag metadata and cached bytes use the same URL/digest validation in both transports. 304 responses preserve cached bytes; changed 200 responses replace them. No freshness skipping or stale-on-error fallback was added.
- Downloads publish each file atomically. TaskGroup cancels/joins outstanding work on failure; sample.json is published only after all files succeed. Existing sample.json is removed before starting a refresh.
- Local HTTP/1.1 tests exercise connection reuse and the concurrency bound, shared cache behavior for both transports, and failed parallel refreshes. Thirty-one downloader/benchmark checks and the regular 180-test non-live suite pass; total package coverage remains 99.08%.

## Limits

Three runs per variant, executed in a fixed order on a local x86_64 machine. DNS, TLS, server caches, network conditions and realtime changes affect timings. This is an end-to-end observation, not an isolated attribution of CPU/TLS costs or a service latency guarantee. No constrained-device results are claimed. Body byte counts exclude HTTP headers/TLS and aiohttp may report decompressed bytes.

## Reproduce

```bash
uv run --locked python experiments/cdn/bench_downloader.py --date 2026-11-12 --pages 12 --compare-transports --concurrency 4 --write results.json
```

Pick a date in current CDN coverage. Raw per-request evidence: [JSON](2026-11-11-fedora-pooled-downloader.json). Earlier sequential measurements: [original report](2026-11-11-fedora-downloader.md).
