# Composition, stop status, extra stops and occupancy: decisions (#265)

Evidence from #249, #263, #264 plus new checks on 11 November 2026 (late evening, Brussels). Script:
`verify_status_clock.py`. "CDN backend" means the backend planned in #250.

## Decisions

| Feature | Decision | Source found? |
|---|---|---|
| Composition (`get_composition`) | **Deprecate on the CDN backend.** It raises `NotSupportedError`. The API backend keeps serving it until the switch-off. | No open source. |
| Occupancy (`occupancy`) | **Optional, `None` on the CDN backend.** Not implemented. | No computed scores. A crowd-sourced dataset exists, but its endpoint is down. |
| `left` / `arrived` | **Approximate from the clock and the realtime delay, and say so in the docs.** The fields stay `bool`. | No status source; the clock rule matched the live API 95 to 99%. |
| `is_extra` / `is_extra_stop` | **Optional, `None` on the CDN backend** ("not reported"). Not `False`. | No source; the feeds never contain added trips. |
| Disturbances, connection `alerts` / `remarks` | Already settled in #263 and #264: disturbances can be rebuilt from the RSS feed (licence open); connection alerts and remarks have no source, so they are empty/`None`. | See those results. |

### Composition

- The only source is SNCB's RIV API (`https://mobile-riv.api.belgianrail.be`, endpoint
  `/api/v1/commercialtraincompositionsbetweenptcars`), which iRail's server calls with an application key in
  `x-api-key`. Anonymous access answers `403 ... error 7501 : _API-Key : Incorrect credential received`.
  iRail's own CDN plans (`specs/riv.md`) say the same: "access requires the application's RIV key", and "API access
  and public redistribution are separate source properties". The key is the application's, not something a pyrail
  user can obtain; I did not look for ways around that.
- No open composition dataset on transportdata.be, the BMC portal, or the GTFS feeds (#249, #264).
- Home Assistant's NMBS integration does not use `get_composition` (checked its source), so the impact on the known
  downstream user is nil.
- The deprecation message should say: composition needs SNCB's private API; use the API backend while
  `api.irail.be` runs.
- Only open question that is not ours to answer: whether SNCB would issue keys to third parties. Asking costs one
  email (`gtfs@sncb.be`, the contact on the SNCB dataset); it is not planned work.

### Occupancy

- The API's `occupancy` values come from RIV, the same private source (iRail's `specs/enrichment.md` maps RIV
  `1 → low, 2 → medium, 3 or 4 → high`). Not obtainable.
- The only public dataset is "Occupancy scores SNCB" on transportdata.be (publisher iRail, licence **CC0**): raw
  user reports of low/medium/high per trip, at `https://gtfs.irail.be/feedback/`. Today that URL answers **503**
  (and `gtfs.irail.be` redirects to `gtfs.flatturtle.cloud`, so the dataset entry may be out of date). Its format is
  listed as JSON with no schema or description, so I could not check what a record contains or how many there are.
- Even working, it would be crowd reports that pyrail would have to aggregate itself, not the scores the API returns,
  so a drop-in `occupancy` would be a different, weaker thing. Not worth building on a dead endpoint.
- Decision: `occupancy` becomes optional and the CDN backend returns `None`. Revisit only if the feedback endpoint
  comes back with a documented schema (CC0 would make it easy to adopt).
- Home Assistant's NMBS integration does not read `occupancy`.

### `left` and `arrived`

The CDN data has no status, and no vehicle-positions feed exists (#264). The approximation is: `left` is true when
scheduled departure plus delay is not after now; `arrived` likewise with the arrival time.

`verify_status_clock.py` against the live API (3 stations, 9 trains, one evening):

| Check | Equal to the API |
|---|---|
| liveboard `left` | 35 / 37 (95%) |
| vehicle stops, `left` | 137 / 139 (99%) |
| vehicle stops, `arrived` | 136 / 139 (98%) |

- All 7 disagreements have the same direction: the clock says "already" and the API still says "not yet". The API
  flips at the physical event, so the clock is early by seconds (5 of 7 within 90 s) and in one case 262 s. It is
  never late. In practice: a train shown as departed can be up to a few minutes early.
- One evening and a small sample, at a quiet hour; a rush-hour run would show more.
- What matters downstream: Home Assistant uses `connection[0].departure.left` to skip a connection that has
  already left. For that use the clock rule is the right answer by construction, and the planner would not
  offer a departed connection in the first place.
- iRail's own CDN spec argues against inferring status from the clock ("Do not infer `reported` from the clock
  having passed"). That is about publishing observed states as data. pyrail's `left` is a convenience flag, so the
  approximation is acceptable if the docs say it is estimated. Cancelled calls: `left` stays false.
- Because the rule always yields an answer, these fields stay `bool` (no `None`).

### Extra trains and stops

- The GTFS-RT trip updates of the HAFAS feed and of the CDN contain only `SCHEDULED` (188) and `CANCELED` (1) trips,
  and `SCHEDULED` (1058) and `SKIPPED` (16) stops; BMC's contain `SCHEDULED` trips and `SCHEDULED`/`NO_DATA` stops.
  **No `ADDED`, `NEW`, `UNSCHEDULED` or `DUPLICATED` anywhere**, in one snapshot per feed. The alerts feed has no
  scope that could mark one either (#264).
- So the CDN backend cannot know a train is extra. `False` would claim "this is a regular train" when we do not know;
  `None` says "not reported". Home Assistant exposes `extra_train` from `is_extra`, so it will show `None` there. That belongs
  in the migration guide.
- If a feed starts sending added trips, the overlay (#253) should count them and surface them rather than drop them
  silently; that is a later change, not part of this decision.

## Follow-up items for the other issues

Not posted anywhere; for the maintainer to paste or ask me to post.

**#250 (backend abstraction)**
- [ ] `NotSupportedError` raised by the CDN backend's `get_composition` with the message above.
- [ ] CDN `get_liveboard`/`get_connections`/`get_vehicle` fill `left`/`arrived` from the clock and delay; document it as an estimate.

**#251 (optional fields)**
- [ ] `occupancy` (liveboard departure, connection departure, vehicle stop): `Occupancy | None`.
- [ ] `is_extra` and `is_extra_stop`: `bool | None`.
- [ ] `left` and `arrived`: stay `bool`.
- [ ] Connection `alerts` / `remarks`: `None` or empty (from #264).

**#260 (release and migration guide)**
- [ ] Not supported on the CDN backend: `get_composition`. `occupancy` is always `None`; `is_extra` / `is_extra_stop`
      are always `None`; `left` / `arrived` are estimates from the clock (95 to 99% agreement, early by up to a few minutes).
- [ ] Tell the Home Assistant NMBS maintainers: the `extra_train` attribute becomes `None`; `occupancy` and composition
      are not used by the integration.
- [ ] Disturbances: depends on the licence answer in #263 / #264.

## Not done

- Rush-hour run of `verify_status_clock.py`; international trains; cancelled trains.
- Asking SNCB about RIV keys or the feedback dataset.
- Checking whether any other consumer of pyrail uses composition or occupancy (only Home Assistant's NMBS integration
  was checked).
