# Official GTFS Realtime endpoints, alerts and licences (#264)

Scripts: `decode_alerts.py` (and `disturbances_feed.py` from #263). Sample: `2026-11-11-alerts.pb` (48 alerts, 11 November
2026). All requests were made anonymously, without a key, on 11 November 2026 around 22:50 (Brussels).

## Verdict

- **The official endpoints are known and need no key to try.** Two operators of the same data publish them: SNCB's own
  HAFAS server and the Belgian Mobility Company (BMC) open-data platform.
- **There is an official alerts feed** (BMC, `rt/alert`). It carries the same 48 messages as the RSS feed, in all four
  languages at once, plus cause and effect. It cannot replace the RSS feed for `get_disturbances` completely
  (see below), and it cannot feed connection `alerts`/`remarks`.
- **There is no vehicle-positions feed** for NMBS/SNCB, so `left`/`arrived` has no source here.
- **Licence: sources disagree, and that is a blocker to settle** before pyrail ships a default that uses any of this.
  A person must read the terms or ask SNCB (see "Licences").

## Endpoints

| Feed | URL | Key | Result |
|---|---|---|---|
| Trip updates, SNCB HAFAS | `https://sncb-opendata.hafas.de/gtfs/realtime/d22ad6759ee25bg84ddb6c818g4dc4de_TC` | none | 200, protobuf, 59 KB, 189 trips, GTFS-RT 1.0. The token in the path is published in iRail's `gtfs-rt-comparison` README (`iRail-cdn/specs/sources.md` names the host but elides the path); it may change. |
| Trip updates, BMC | `https://api-management-discovery-production.azure-api.net/api/gtfs/feed/nmbssncb/rt/trip-update?format=protobuf` | none (anonymous tier) | 200, protobuf, 33 KB, **62 trips**. Without `format=protobuf` it answers JSON. |
| **Alerts, BMC** | `.../api/gtfs/feed/nmbssncb/rt/alert?format=protobuf` | none (anonymous tier) | 200, protobuf, 119 KB, 48 alerts, GTFS-RT 2.0. |
| Vehicle positions | `.../rt/vehicle-position`, `-positions`, `vehicleposition`, `position(s)`, `vehicles`, `occupancy` | | all 404. BMC's catalogue lists exactly two real-time GTFS-RT feeds for NMBS-SNCB: "TU, SA". |
| SIRI situation-exchange, BMC | `https://api-management-discovery-production.azure-api.net/api/siri/feed/nmbssncb/situation-exchange?format=json` | none | 200, JSON, 107 KB: the same 48 alerts as SIRI `Situations`. |
| SIRI estimated-timetable, BMC | `.../api/siri/feed/nmbssncb/estimated-timetable?format=json` | none | 200, JSON, 190 KB. |
| SIRI vehicle-monitoring | `.../siri/feed/nmbssncb/vehicle-monitoring` | | 404 (BMC lists it for LETEC only). |
| Static GTFS, BMC | `.../api/gtfs/feed/nmbssncb/static` | none | 200, zip, 19 MB. |

- **The CDN republishes the HAFAS feed, not BMC's.** The CDN's `trip-updates.pb` and the HAFAS feed hold the same
  189 trip ids (the bytes differ only by timestamp); BMC holds a 62-trip subset. iRail's own
  `specs/sources.md` says the same ("Open feed `sncb-opendata.hafas.de`"). The CDN's `irail.json` however labels the
  feed "the open Belgian Mobility feed (NMBS/SNCB, CC BY 4.0)" — that label does not match its source.
  (BMC strips a `gt:nmbssncb:` prefix from trip ids; the 62 shared ids are otherwise equal.)
- **The portal's documented hostnames do not resolve.** Its knowledge base lists
  `opendata-discovery-gtfs-realtime.api.production.belgianmobility.io/api/gtfs-rt/nmbssncb/{TripUpdates,ServiceAlerts}.pbf`
  and a `-gtfs-static` twin; DNS fails for them (iRail's comparison repo saw the same in October 2026). The working
  host is the `api-management-discovery-production.azure-api.net` one, with the paths in the table (the one the
  transportdata.be dataset also uses for `static`). Expect these URLs to move.
- Freshness: protobuf headers advanced about 30 s per fetch (BMC alert header `1794433894`, `...4016`, `...4077`).
  `Cache-Control` was `max-age=15` on the CDN copy; BMC sent `Last-Modified` and a weak `ETag` but no `Cache-Control`.

## What the alerts contain

48 alerts today, every one with the same shape:

- `header_text`, `description_text`, `url`: translations in all of nl, fr, de, en.
- `cause`: `CONSTRUCTION` for 46, `UNKNOWN_CAUSE` for 2. `effect`: `NO_SERVICE` 25, `MODIFIED_SERVICE` 20, `DETOUR` 2,
  `UNKNOWN_EFFECT` 1. All 48 URLs say `tplParamHimMsgInfoGroup=works`, so every alert is a planned one today; as with the
  RSS feed (#263) **no unplanned (`trouble`) alert was available to look at**.
- **`informed_entity`: one `agency_id: nmbssncb`, nothing else, for all 48.** No route, stop or trip scope.
- **No `active_period`** for any alert. (SIRI `ValidityPeriod.StartTime` is the time of the fetch, and `Affects` is `{}`.)
- `description_text` is plain text on one line. Line breaks are gone and the links are reduced to their labels
  ("... En savoir plus sur les bus SNCB (FAQ) Où prendre mon bus ?").

### Against the RSS feed (and the API)

`decode_alerts.py --compare {nl|fr|de|en}`: 48 alerts, 48 RSS items, **0 differences** in title, description (after
flattening whitespace) and type, in all four languages. The `messageID=` numbers in the alert URLs are the RSS
items' numbers (48 of 48).

| `get_disturbances` field | From the alerts feed? |
|---|---|
| `title` | yes (`header_text`) |
| `description` | yes, but flattened: no line breaks |
| `type` | yes: `works` in the URL, or `cause` = `CONSTRUCTION` |
| `link` | yes (`url`, per language) |
| `richtext` | no (no markup) |
| `descriptionLinks` | **no**: the link targets are not in the text |
| `timestamp` | **no**: no publication time in the alert (RSS has `pubDate`) |
| `id` | not stable: `entity.id` (`rs:nmbssncb:<hash>`) is **new on every fetch**, also for unchanged alerts (0 of 48 ids repeated between three fetches). The URL's `messageID` is the stable key. |

So the alerts feed has the better official standing and all languages in one request, but it loses
`descriptionLinks` and `timestamp`. The RSS feed is the one that rebuilds the whole `Disturbance`.

### Connection `alerts` / `remarks`

Not possible from this feed: alerts are scoped to the agency only, with no stop, route or trip and no validity
period, so they cannot be attached to a connection or a time window. (The CDN's `connectionEnrichment`, which is
where such data would go, is `unavailable` in `irail.json`.) A text match on station names in the titles would be a guess,
which this spike does not attempt.

### Vehicle positions and `left` / `arrived`

There is no vehicle-positions feed. The trip updates carry predicted/actual stop times but no "has left" flag;
whether `left`/`arrived` can be approximated from them is a separate question for #253's stop-status work.

## brail2gtfs-rt (iRail)

`iRail/brail2gtfs-rt` (Java, MIT, last pushed February 2025, 2015 origin): "service alerts and trip updates" for the
old iRail GTFS, with "information scraped from the NMBS website and the iRail API". It is built on a deprecated
dataset (`gtfs.irail.be/nmbs/nmbs-latest.zip`) and `gtfs.irail.be` now redirects to FlatTurtle. **Not a candidate**:
the official BMC alerts feed does the same job with an official source. Its code's licence (MIT) does not decide the
terms of the scraped data.

## Licences

| Source | Stated licence / terms |
|---|---|
| BMC platform terms of use (`data.belgianmobility.io/en/terms.html`, effective 1 January 2026) | **CC BY 4.0** for all datasets "unless otherwise stated", each operator being the licensor; commercial reuse allowed. Attribution minimum: `Source: [PTO name] – Open Data – [date of dataset update]`. |
| BMC access tiers | **Anonymous: no registration, 100 requests/day and 10/minute**. Standard: free registration with an API key, 12,000/day and 500/minute. Gold: on request. Keys are personal and non-transferable, so a library cannot ship one. HTTP 429 on excess. No SLA for Anonymous or Standard. |
| transportdata.be dataset "SNCB GFTS - scheduled timetable and real-time data" (SNCB's own record, modified 8 September 2026) | licence **"Other (Non-Commercial)"** (`other-nc`), `isopen: false`, usage conditions "contractual arrangement": "Access and usage of SNCB's data is subject to the terms and conditions of a license agreement which can be requested on `belgiantrain.be/en/support/forms/public-data`". Contact `gtfs@sncb.be`. Its only resource is the static feed. |
| iRail CDN (`irail.json`) | `gtfs-rt` source marked CC BY 4.0 (but see above: it republishes the HAFAS feed). |
| SNCB HAFAS feed | no terms found. |
| RSS feed (#263) | no terms found. |

**The two official statements contradict each other**: BMC says CC BY 4.0 with commercial reuse, SNCB's own catalogue
record says non-commercial under a licence agreement. I cannot tell which one applies to the BMC-served copy, and the
SNCB page that would explain it (`belgiantrain.be/.../public-data`) returns a captcha (403) from here.
**A person needs to settle this** (read the page in a browser, or write to `gtfs@sncb.be` / BMC) before pyrail points
at any of these URLs by default.

**The anonymous tier is too small for polling.** 100 requests a day is about one request every 15 minutes, and 10 a
minute is shared by everything behind one IP. A Home Assistant integration refreshing alerts every 5 minutes would
need 288 a day. Real use needs each user to register for their own key, or iRail/pyrail to cache and republish (the
CDN already republishes the trip updates), which brings back the licence question.

## Not done

- No unplanned (`trouble`) alert or non-`CONSTRUCTION` cause was available to look at.
- I did not test a registered key, the 429 behaviour, or whether the anonymous quota is really enforced (I made a few dozen
  anonymous requests to the BMC host, without a 429).
- Whether the HAFAS feed's token in the URL rotates.
- Whether BMC's 62-trip subset is a deliberate filter (it affects which feed is the better realtime source).
- Whether the RSS or the alerts feed leads: that depends on the licence answer above.
