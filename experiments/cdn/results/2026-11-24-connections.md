# CDN `get_connections`: time, memory and agreement, 2026-11-24

Closes the measurement task of [#258](https://github.com/tjorim/pyrail/issues/258). Raw numbers:
[`2026-11-24-connections.json`](2026-11-24-connections.json) (`bench_connections.py --repeat 7`). Agreement with the
API and the reference planner: [`2026-11-24-journeys.md`](2026-11-24-journeys.md) (`compare_journeys.py --pairs 100`).

## Setup

- x86_64 desktop, 8 cores, Python 3.12.16, Linux 7.0, live CDN and iRail API on 2026-11-24. **Not a Home Assistant
  Yellow**: that device was not reachable this time, so the Yellow figures below are estimates, not measurements.
- Each query ran in a fresh process, seven times. *Cold* is the first call (manifest, connection pages, Arrow
  decode, realtime feed, scan). *Warm* is the next call on the same backend, as a Home Assistant poll would be.
- Queries for 2026-11-25 at 09:00 Belgian time: **short** Brussels-North to Antwerpen-Centraal, **long** Oostende to
  Arlon, **arrive-by** Brussels-Central to Gent-Sint-Pieters. Every one returned six journeys.

## Measured on the desktop (median of seven; range in brackets)

| Query | Cold total | of which load / realtime / route | Warm total (route only) | Peak RSS |
|---|---|---|---|---|
| short | 1145 ms (1109-1409) | 466 / 366 / 296 ms | 310 ms (307-349) | 126-134 MiB |
| long | 1557 ms (1528-1579) | 463 / 359 / 725 ms | 705 ms (700-723) | 127-135 MiB |
| arrive-by | 980 ms (964-1008) | 444 / 336 / 185 ms | 181 ms (180-207) | 112-113 MiB |

A warm call costs the route phase only. The decoded tables and pages stay cached, and the realtime merge is shared by
queries between two feed refreshes (a unit test pins this). Each search loads the six-hour window plus a six-hour journey
allowance (a few 1.5 MB pages). Sparse routes widen to 12 and 24 hours, which loads more pages.

## Estimate for a Home Assistant Yellow

The reader benchmark of 11 November ([`2026-11-11-yellow.md`](2026-11-11-yellow.md)) found the Yellow (Raspberry Pi CM4,
under normal Home Assistant load) 5 to 9 times slower than this class of desktop, uniformly across readers. Applying
that factor to the CPU phases gives a warm poll of about 1.6 to 2.8 s for a short route and 3.5 to 6.3 s for the
longest one, and a cold first call of 5 to 14 s. Memory is not scaled: about 130 MiB peak for the whole process, against
the 0.9 to 1.0 GB the device had free. Network time comes on top of the cold figures.

Because that much CPU time would freeze Home Assistant's event loop, the CPU-bound steps (Arrow decoding, realtime
merge, journey, liveboard and vehicle building) run in worker threads. With a heartbeat task running next to a cold
Oostende-Arlon search the worst event-loop stall was 35 ms; the call itself took 1.8 s. The threads share the GIL, so
the total CPU time is unchanged and a slow device still needs seconds to answer.

**Still open:** a measurement on the Yellow itself. Run
`uv run python experiments/cdn/bench_connections.py --repeat 5 --write yellow.json` on the device (the script needs
`pyrail[cdn]` and `aiohttp` only) and add the file here.

## What changed in the router to get here

| Step | Long query, route phase (x86) |
|---|---|
| First connection scan (committed before this work) | 1780 ms |
| Multi-label scan, testing dominance before the transfer rules | 1290 ms |
| Trips that no rule names share one arrival front per stop | 730 ms |

## Agreement

100 random pairs of 25 Belgian stations at five times of day, every fifth search arrive-by, scheduled times and transfers
compared. The CDN backend returns the timetable the API does (six vehicles compared stop by stop, and the live parity tests), so differences come from the
planners and from trains the CDN does not publish.

| Against | Compared searches | Other options | Shared with the CDN | Only the other source | Only the CDN |
|---|---|---|---|---|---|
| `@irail/planner` 0.1.3 | 100 | 600 | 595 (99.2 %) | 5 | 5 |
| iRail API | 90 (10 failed on the API side) | 547 | 509 (93.0 %) | 38 | 31 |

- **API-only options** are almost all journeys that use Eurostar (`EUR`), Thalys, `ICE` or an international `EC`/`NJ`
  leg. The CDN publishes none of the Eurostar, Thalys or ICE services, only two cross-border products. This is a data
  gap, not a planner difference, and the CDN's `no_international_trains` matches all six API options to Luxembourg and three of six to Paris Nord.
- **The rest** are the sixth or seventh option (the API sometimes lists seven), overnight journeys that one planner
  lists and the other does not, and bus legs, which the reference planner includes and `automatic` excludes.
- The 10 API failures are a separate pyRail bug in the API backend: a journey with a walking leg (for example
  to Jambes-Est) has no `departureConnection` on the walking arrival, so the response fails model validation.

## Correctness checks

`tests/cdn/test_routing_oracle.py` compares the scan with an exhaustive search on random networks that mix platforms,
minimum change times, transfer rules (timed, minimum, forbidden, in-seat), pickup and drop-off restrictions, delays,
cancellations and skipped stops, from a random start time and back from a random deadline. The committed run uses 500
networks per combination. A one-off run of 15 000 found one planner bug, an in-seat continuation after a canceled last
connection (fixed, with a unit test), and settled two behaviours the oracle now encodes: an in-seat link needs no
drop-off or pickup at the junction and tolerates a platform change inside the station. Journeys cut off at a connection
page boundary, which the oracle cannot see, came from the live comparison and are fixed by loading a journey allowance.
