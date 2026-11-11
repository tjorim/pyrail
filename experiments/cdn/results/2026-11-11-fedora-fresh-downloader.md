# Freshness-aware CDN cache refresh

Measured locally at 2026-11-11T19:18:25.925158+00:00, Python 3.12.13, `Linux-7.2.15-300.fc45.x86_64-x86_64-with-glibc2.44`. Runtime base `b07d10f343b326ca7032cf850dcf0732b5dda6d6` plus the accompanying freshness implementation and benchmark changes. Release `nmbs-sncb-20261111-5c05082d`, sampled date 2026-11-12.

## Measured improvement

Both variants use connection pooling, concurrency four, the same disk cache and the same 19-resource sample (manifest, four tables, extensions, realtime, twelve connection pages). Each has one excluded priming pass, then three timed passes.

| Policy | Samples (ms) | Median (ms) | HTTP requests per warm pass | Local fresh hits |
|---|---|---|---|---|
| Force ETag revalidation | 276.808, 329.952, 316.625 | 316.625 | 19, 19, 19 | 0, 0, 0 |
| Respect explicit freshness | 44.452, 44.81, 43.94 | 44.452 | 0, 0, 0 | 19, 19, 19 |

The median fell from **316.6 ms to 44.5 ms**, a **7.1× speedup**. All forced-revalidation responses were 304; freshness-aware runs made no HTTP requests because all nineteen cache entries were still fresh. Both transferred zero response-body bytes.

The remaining time includes reading and hashing cached bodies, checking persistent metadata, parsing the manifest, scheduling work and atomically rewriting the selected sample files. Python process startup, Arrow decoding and routing are excluded. Filesystem caches are warm; these are not disk-cold or constrained-device measurements.

## Freshness behavior

- Cache-Control max-age supplies an explicit lifetime. Expires is used only if max-age is absent. Date, Age and request/response delay reduce remaining freshness using the age calculation from [RFC 9111 §4.2.3](https://www.rfc-editor.org/rfc/rfc9111.html#section-4.2.3). There is no heuristic TTL.
- Fresh bytes are reusable even without an ETag. Stale bytes use conditional revalidation when a validator exists, otherwise a full GET. Old cache metadata lacking freshness information revalidates on first use.
- A 304 updates freshness and supplied policy headers, retaining omitted Cache-Control/Expires/Vary metadata. Date and Age are evaluated from the validation response. A 200 replaces policy, validator and bytes.
- no-cache requires revalidation; no-store removes the HTTP cache entry. Invalid or duplicate max-age, invalid Age and unknown Vary fields do not grant freshness. The fixed User-Agent, identity Accept-Encoding and URL-derived Host are stable between transports.
- Cached body digests are checked before fresh reuse. Missing/corrupt bytes and backwards local clock movement require a request. HTTP/network errors for required revalidation still fail rather than silently serving stale bytes.
- Each URL has its own deadline. Tests verify that an expired realtime resource revalidates while a still-fresh timetable resource makes no request. The observed CDN policies are max-age=600 for manifest/timetable files and public max-age=15 for realtime; upstream age can shorten these intervals.

## Original API comparison

The same benchmark also measured the public IRail client: warmed medians **55.7 ms** for Brussels-South–Antwerpen-Centraal and **39.1 ms** for Oostende–Arlon, with six/seven returned alternatives. HTTP, JSON and model parsing are included; priming and one-second pacing are excluded. API responses were 200 without ETags.

A fully fresh sample check is now in the same latency range as one API request in this run. This is not an equivalent journey comparison: the CDN operation checks/materializes a shared bulk dataset and does not decode Arrow or calculate journeys. Retain decoded data across journey queries and refresh independently. When a cache entry expires, its HTTP latency returns; the all-fresh 44 ms result must not be presented as the cost of every future refresh.

## Validation and reproduction

Fifty-five downloader/benchmark checks pass, including freshness persistence, expiry, partial resource expiry, 304 policy renewal, Age/Date handling, no-cache/no-store, missing validators, malformed directives, clock rollback, corrupt bodies, connection reuse and bounded concurrency. The 180-test regular non-live suite passes with 99.08% package coverage; lint, formatting and type checks pass. Nine live tests were excluded.

```bash
uv run --locked python experiments/cdn/bench_downloader.py --date 2026-11-12 --pages 12 --concurrency 4 --compare-freshness --write results.json
```

Choose a date within current CDN coverage. `fetch_data.py --revalidate` bypasses local freshness for diagnostics. A normal run respects cached deadlines. Three samples in fixed order are a small local snapshot, not a latency guarantee; no Raspberry Pi-class hardware was available. Raw evidence: [JSON](2026-11-11-fedora-fresh-downloader.json).
