# Disturbances from the NMBS RSS feed (#263)

Script: `disturbances_feed.py`. Sample: `2026-11-11-disturbances-feed-en.xml` (English feed, 11 November 2026, 48
items). Compared with the live API `https://api.irail.be/disturbances/` on the same day.

## Verdict

**The data can be rebuilt exactly; whether we may use it is not settled.** The feed is the one iRail itself uses,
the rebuilt response was identical to the API's in all four languages (nl, fr, de, en; 48 items each, 0
differences), and the result loads into `DisturbancesApiResponse`. What is missing is the terms of use.

## The feed

- URL (from iRail's own server, `NmbsRssDisturbancesClient` in iRail/iRail, which uses plain HTTP):
  `https://www.belgianrail.be/jp/sncb-nmbs-routeplanner/help.exe/{nl|fr|de|en}?tpl=rss_feed`
- Both `http://` and `https://` answer 200 with the identical document (no redirect); the script uses HTTPS. No key
  or cookie needed. It answered 200 with `Content-Type: text/html`
  (the body is RSS 2.0), 46 to 55 KB. The `belgiantrain.be` pages, by contrast, answer 403 / a Cloudflare captcha
  from this machine; `belgianrail.be` did not. `robots.txt` on `belgianrail.be` only blocks one TV page; the feed
  sends `X-Robots-Tag: noindex, noarchive, nosnippet`.
- RSS 2.0 `<channel>` (title "Works"/"Werken"/..., `pubDate`) with `<item>`s: `title`, `description` (HTML in CDATA),
  `link`, `pubDate`, `guid`, `dc:creator` (empty).
- The channel is named "Works" and all 48 items today are works, but iRail's code handles both kinds from this one
  URL (`tplParamHimMsgInfoGroup=works` in the link means planned, anything else means disturbance), and the
  recorded January 2025 API response had a `trouble` item. **I have not seen an unplanned item in the live feed**:
  there was none on the day. Check again during a real disruption.

## Field by field

| API field | Rebuilt from | Notes |
|---|---|---|
| `title` | `<title>` | as is |
| `description`, `richtext` | `<description>` | `<br>` becomes a newline, other tags are removed, runs of spaces collapse, a space before a newline stays. The API returns the same text in both fields today (the January 2025 recording had HTML in `richtext`). |
| `type` | `<link>` | `tplParamHimMsgInfoGroup=works` is `planned`, otherwise `disturbance`. |
| `timestamp` | `<pubDate>` | epoch seconds. Matches the API for all 48. |
| `link` | first `<a href>` in the description, else `<link>` | |
| `descriptionLinks` | every `<a href>` in the description | `number` is the count; if there are none, one entry pointing at `<link>` with iRail's "Read more" text (nl "Lees meer", fr "Lire plus", de "Weiterlesen"). |
| `id` | position in the feed | `"0"`, `"1"`, ... It is not the NMBS `messageID`, so it is **not stable** between calls. A stable id would be `messageID=` from `<link>` (iRail's new server uses that internally). |
| top-level `timestamp` | channel `pubDate` | the API puts its own cache time here; we do not compare it. |
| top-level `version` | constant `"1.4"` | the API said 1.3 in the January 2025 recording and 1.4 now. |

The `description` text for items with no HTML links in the feed is plain; 21 of 48 items had no `<a>` in the
English feed and rebuilt correctly.

## Last known status

`LastKnownStatus` fetches, converts, and writes the result atomically to disk. If the fetch fails or the body is not
an RSS document (a captcha or error page), it serves the stored answer, for up to 12 hours (iRail's own backup
window), and raises if there is nothing recent. Offline tests cover: fresh, outage, captcha body, nothing stored,
other language, too old, and a corrupt cache file.

## Terms of use: not found

- I found no published terms for this feed. SNCB's public-data page (`belgiantrain.be/.../public-data`) is behind
  the captcha from here, so I could not read it. Older SNCB material (2017) says its open data is free but
  needs a signed contract; that covers the GTFS feeds, and I could not tell whether it covers this RSS feed.
- Nothing documents rate limits. The script makes one request per call; iRail caches the answer for 3 minutes.
- **Needs a person to decide:** read the terms on the SNCB page in a normal browser, or ask SNCB / iRail, before
  pyrail ships a default that polls this URL. Until then, this stays in `experiments/`.

## Not done

- The `get_disturbances` method of the CDN backend (#250) itself: this is a prototype, not part of the package.
- Behaviour during a real unplanned disruption; how long NMBS keeps items after
  the works end (iRail passes them through unchanged).
- Alerts from GTFS Realtime remain an open alternative (#249): the official realtime endpoints are still unknown.
