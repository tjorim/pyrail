# Moving pyRail to the Linked Connections (CDN) backend

iRail plans to switch off `api.irail.be` in 2027 and to replace it with static Linked Connections files on a CDN
([#245](https://github.com/tjorim/pyrail/issues/245), [#246](https://github.com/tjorim/pyrail/issues/246)).
pyRail has a second backend, `CdnBackend`, that serves the same `IRail` methods from those files. This guide
explains how to switch, what changes, and what is not available.

The CDN backend is **opt-in**. Nothing changes until you pass it to `IRail`. This guide describes the beta; the
details can still change while the Linked Connections specification is alpha.

## Switching

Install the extra, which adds the GTFS Realtime decoder, and pass the backend:

```bash
pip install "pyrail[cdn]"
```

```python
from pyrail import CdnBackend, IRail

async with IRail(lang="en", backend=CdnBackend()) as api:
    stations = await api.get_stations()
    board = await api.get_liveboard(station="Brussels-Central")
    journeys = await api.get_connections("Ghent-Sint-Pieters", "Brussels-Central")
```

- Without the extra, stations and the static timetable work, but anything that needs real-time data raises
  `NotSupportedError("Install pyrail[cdn] to use realtime CDN services")`.
- `session`, `max_retries` and `request_timeout` belong to the API backend. With a custom backend, configure the
  backend instead: `CdnBackend(lang, session=my_session)`. `IRail` raises `ValueError` if you pass both.
- The rate limiter and the ETag cache only apply to the API backend. The CDN backend caches the decoded files
  itself and refreshes the real-time feed every 30 seconds.
- Station names in requests follow `lang`: use `Brussels-Central` with `lang="en"` and `Brussel-Centraal`
  with `lang="nl"`. Station ids work in every language.

To keep using the API for now, change nothing, or pass `ApiBackend()` explicitly.

## What each method does

| Method | CDN backend |
|---|---|
| `get_stations` | Supported. Combines the timetable stops with the curated station catalog, so it can list stations the API does not, and a few ids or translations differ. |
| `get_liveboard` | Supported. One hour from the requested time. The CDN board and the API board can list different calls, because the API uses SNCB's RIV feed and the CDN uses the published timetable plus GTFS Realtime. |
| `get_vehicle` | Supported. Uses the Belgian service date and returns the first run of that vehicle number on the date. |
| `get_connections` | Supported. pyRail plans the journeys itself (connection scan), see below. |
| `get_composition` | **Not supported.** It needs SNCB's private API. It raises `NotSupportedError`; stay on the API backend while it exists. |
| `get_disturbances` | **Not supported yet.** The CDN has no disturbances file. A source exists, but its terms of use are unanswered ([#271](https://github.com/tjorim/pyrail/issues/271)). It raises `NotSupportedError`. |

`NotSupportedError` is a `PyRailError`, so existing `except PyRailError` blocks catch it.

## Journeys

`get_connections` returns up to six options, like the API: the fastest ones plus journeys with fewer transfers
that arrive within an hour of the fastest. It starts with the next six hours of departures and widens to 12 and
24 hours. It applies the published minimum transfer times, transfer rules, platform changes, in-seat
continuations, skipped stops and real-time delays, and lists canceled journeys next to the usable ones. When it
finds nothing it raises `NotFoundError`, as the API does.

Differences to expect:

- **International trains.** The CDN publishes no Eurostar, Thalys or ICE services and no stations outside Belgium,
  so journeys that use them are missing or longer. `type_of_transport="no_international_trains"` works and
  excludes EC, EN, EST, EUR, ICE, NJ, THA and TGV trips; buses are left out unless it is `"all"`.
- **Options.** Against the API, 93 % of 547 options matched in a comparison of 100 random Belgian searches. Against
  the reference planner `@irail/planner` it was 99 % of 600. The sixth option, overnight journeys and buses
  account for most of the rest. Details: [`experiments/cdn/results/2026-11-24-journeys.md`](experiments/cdn/results/2026-11-24-journeys.md).
- **Speed.** A search takes about 0.2 to 0.7 s on a desktop CPU once the data is cached, and 1 to 1.6 s on the first
  call. On a Raspberry Pi class device expect 5 to 9 times that (an estimate; it has not been measured on a
  Home Assistant Yellow yet, see [#258](https://github.com/tjorim/pyrail/issues/258)). The CPU-bound steps run in
  worker threads, so the event loop is not blocked. Memory peaks at about 130 MiB.

## Fields that can be missing

These fields have no source in the CDN data. They are `None` (or an empty list) in CDN responses, and the models
now allow it. Check for `None` before using them.

| Field | CDN backend |
|---|---|
| `occupancy` (departures, arrivals, vehicle stops) | `None` |
| `is_extra` (departures, arrivals), `is_extra_stop` (stops) | `None` |
| `alerts`, `remarks` on a connection | empty lists |
| `VehicleInfo.longitude`, `latitude` | `None` |
| `PlatformInfo.normal` | `None` |
| `departure_connection` | `None` for walking legs (also on the API, since 0.7.0) |
| `platform`, `platform_info` | `None` when the timetable has no platform |

`left` and `arrived` are **estimates**. The CDN has no stop status, so pyRail derives them from the clock and
the real-time delay. They agreed with the API in 95 to 99 % of the calls we compared. The estimate can say a
train has left before it did.

## For Home Assistant's NMBS integration

- It does not read `occupancy` or composition, so those gaps do not affect it.
- The `extra_train` attribute becomes `None` on the CDN backend.
- It uses `departure.left` only to skip a connection that has already left. With the estimate, a connection that
  is still usable can be skipped when the delay is not yet in the feed.
- It needs `pyrail[cdn]` in its requirements.

## Data usage and caching

The backend downloads the manifest, the stop, route, trip and transfer tables, and the six-hour connection pages
(about 1.5 MB each) over HTTPS. A search loads the window it needs plus a six-hour allowance for journeys that
cross a page boundary. The decoded tables are cached in memory, bounded by entry count, and reused until the
manifest says they changed. The real-time merge is shared by queries made between two feed refreshes (30 s).
Nothing is written to disk, so a restart downloads the data again.

## What is planned

1. A beta release with the CDN backend selectable, as described here.
2. A later release that makes the CDN backend the default.
3. Removal or deprecation of the API backend once `api.irail.be` is switched off.

Report problems or surprises in [#246](https://github.com/tjorim/pyrail/issues/246).
