# Warm ETag downloader versus the original API

Measured locally on Fedora at 2026-11-11T19:00:32.800751+00:00, Python 3.12.13, `Linux-7.2.15-300.fc45.x86_64-x86_64-with-glibc2.44`. Runtime checkout `5bbc0c79b29cea138a86b0a74065f0381c293cda`; benchmark script: `experiments/cdn/bench_downloader.py`.

Release `nmbs-sncb-20261111-5c05082d`; sample date 2026-11-12; four core tables, extensions, realtime, manifest and 12 connection pages (19 HTTP requests per complete downloader run). A separate `data/downloader-benchmark` sample/cache directory was primed first. All timings exclude Python process startup.

## Measurements

| Workload | Timing | HTTP responses | Response body bytes |
|---|---|---|---|
| Empty-cache initial download (one run) | 7680.2 ms | 19 × 200 | 23,884,843 |
| Warm downloader run 1 | 1556.2 ms | 19 × 304 | 0 |
| Warm downloader run 2 | 1456.3 ms | 19 × 304 | 0 |
| Warm downloader run 3 | 1465.4 ms | 19 × 304 | 0 |
| Warm API, short (median of 3) | 40.9 ms | 1 × 200 per query | 20,423 per query |
| Warm API, long (median of 3) | 57.6 ms | 1 × 200 per query | 77,718 per query |

Warm downloader median: **1465.4 ms**, range 1456.3–1556.2 ms. Every request sent If-None-Match. All resources, including realtime, were unchanged during these warm passes. A changed resource can normally return 200 on later passes.

API short is Brussels-South to Antwerpen-Centraal; long is Oostende to Arlon. Both ask to depart at 08:00 Europe/Brussels on the sampled date. The API returned six and seven alternatives respectively, with first-arrival timestamps matching the local planner measurements. Each journey had one excluded priming request; the six timed requests were spaced one second apart, outside timed intervals. The public IRail client had ETag support enabled, but these responses supplied no ETag and all returned 200.

## What is included

- Downloader: the actual `fetch_data.main` path, sequential urllib HTTP requests, reading and hashing cached bodies, manifest/metadata handling, and rewriting the selected sample files. The cache remains on disk across downloader instances. Arrow decoding and route planning are excluded.
- API: public `IRail.get_connections`, HTTP, JSON decoding and model deserialization. One aiohttp session is shared across priming and measured calls. Retries are disabled. This is more complete than the earlier raw-HTTP API timing, which did not deserialize pyrail models.
- Body counts exclude HTTP headers and TLS. aiohttp may report decompressed API bytes. A 304 still has request/response overhead even with a zero-byte body.

## Interpretation

ETags eliminate the unchanged response bodies: this refresh avoids re-downloading about 22.8 MiB. They do not eliminate the 19 HTTP round trips or local cache I/O. The current downloader is a bulk sample refresh, whereas the API request returns one journey query with alternatives. Their timings are not equivalent per-query planner latency.

The backend should reuse decoded timetable data across queries and refresh independently of journey requests. Follow manifest/realtime freshness, retain release-specific timetable files, and avoid revalidating every immutable page for every query. Connection pooling or bounded parallelism could reduce refresh latency, but were not implemented or benchmarked here. Current downloader caching deliberately revalidates on every run and does not implement Cache-Control freshness.

Three warm runs provide a small snapshot, not a service latency guarantee. Earlier raw API requests were around 70–80 ms on repeats; this run differs in timing and client path, so do not infer a stable improvement. No Home Assistant-class hardware was measured.

## Reproduce

```bash
uv run --locked python experiments/cdn/bench_downloader.py --date 2026-11-12 --pages 12 --write results.json
```

Choose a date in current CDN coverage. The first downloader pass primes whatever cache is already present and is excluded from warm medians. Use a new `--dir` to measure an empty-cache initial download. Raw request-level results: [JSON](2026-11-11-fedora-downloader.json).
