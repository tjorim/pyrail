"""Decode the official GTFS Realtime service-alerts feed of NMBS/SNCB and compare it with the RSS feed (spike #264).

The Belgian Mobility open-data platform serves NMBS/SNCB alerts as GTFS Realtime, without a key:

    https://api-management-discovery-production.azure-api.net/api/gtfs/feed/nmbssncb/rt/alert?format=protobuf

(Without `?format=protobuf` the same endpoint answers JSON.) This script decodes it to plain dicts, rebuilds what
the iRail `/disturbances` response can be rebuilt from it, and with `--compare` diffs that against the RSS-based
rebuild from `disturbances_feed.py` (#263).

    uv run --group experiments python experiments/cdn/decode_alerts.py [FILE.pb]            # summary + first alert
    uv run --group experiments python experiments/cdn/decode_alerts.py --compare [LANG]     # against the RSS feed

Findings are in results/2026-11-11-realtime-endpoints.md. Needs `gtfs-realtime-bindings` (the `experiments` group).
"""

from collections import Counter
import re
import sys
from urllib.request import Request, urlopen

ALERTS = "https://api-management-discovery-production.azure-api.net/api/gtfs/feed/nmbssncb/rt/alert?format=protobuf"
USER_AGENT = "pyrail-experiments"
_MESSAGE_ID = re.compile(r"messageID=(\d+)")
_GROUP = re.compile(r"tplParamHimMsgInfoGroup=(\w+)")


def fetch(url: str = ALERTS, timeout: float = 30) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def decode(raw: bytes) -> dict:
    """Decode a GTFS Realtime alerts `FeedMessage` to `{"timestamp", "alerts": [...]}` (plain dicts)."""
    from google.transit import gtfs_realtime_pb2 as pb  # noqa: PLC0415 - only needed here

    feed = pb.FeedMessage()
    feed.ParseFromString(raw)

    def translations(text) -> dict[str, str]:
        return {t.language: t.text for t in text.translation}

    alerts = []
    for entity in feed.entity:
        alert = entity.alert
        alerts.append(
            {
                "entity_id": entity.id,  # NOT stable: a new id per fetch, even for unchanged alerts
                "cause": pb.Alert.Cause.Name(alert.cause),
                "effect": pb.Alert.Effect.Name(alert.effect),
                "active_periods": len(alert.active_period),
                "informed": [
                    "trip" if e.HasField("trip") else "stop" if e.stop_id else "route" if e.route_id else "agency"
                    for e in alert.informed_entity
                ],
                "header": translations(alert.header_text),
                "description": translations(alert.description_text),
                "url": translations(alert.url),
            }
        )
    return {"timestamp": feed.header.timestamp, "alerts": alerts}


def message_id(alert: dict) -> str | None:
    """The NMBS `messageID` inside the alert's URL: the only stable identifier an alert has."""
    for url in alert["url"].values():
        found = _MESSAGE_ID.search(url)
        if found:
            return found.group(1)
    return None


def kind(alert: dict) -> str:
    """`planned` or `disturbance`, from the URL's `tplParamHimMsgInfoGroup` (the same rule as the RSS feed)."""
    for url in alert["url"].values():
        found = _GROUP.search(url)
        if found:
            return "planned" if found.group(1) == "works" else "disturbance"
    return "disturbance"


def collapse(text: str) -> str:
    """Flatten whitespace: the alerts keep no line breaks, so this is the strongest comparison possible."""
    return re.sub(r"\s+", " ", text).strip()


def compare(decoded: dict, rss_response: dict, lang: str) -> list[str]:
    """Differences between the alerts and the RSS-based rebuild.

    Items are matched on (title, description with whitespace flattened) in `lang`, as a multiset, because the RSS
    rebuild no longer has the `messageID` for items whose description contains links.
    """
    alerts = Counter(
        (a["header"].get(lang, ""), collapse(a["description"].get(lang, "")), kind(a)) for a in decoded["alerts"]
    )
    items = Counter((i["title"], collapse(i["description"]), i["type"]) for i in rss_response["disturbance"])
    problems = [f"alert only: {t[:50]!r} ({k})" for (t, _d, k) in (alerts - items)]
    problems += [f"RSS only:   {t[:50]!r} ({k})" for (t, _d, k) in (items - alerts)]
    return problems


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if "--compare" in argv:
        import disturbances_feed  # noqa: PLC0415

        lang = args[0] if args else "en"
        decoded = decode(fetch())
        rss = disturbances_feed.convert(disturbances_feed.fetch(lang), lang)
        problems = compare(decoded, rss, lang)
        print(f"{lang}: {len(decoded['alerts'])} alerts, {len(rss['disturbance'])} RSS items, differences {len(problems)}")
        for line in problems[:30]:
            print("  ", line)
        return 1 if problems else 0

    decoded = decode(open(args[0], "rb").read() if args else fetch())  # noqa: SIM115, PTH123
    alerts = decoded["alerts"]
    print(f"feed timestamp {decoded['timestamp']}, {len(alerts)} alerts")
    print("cause/effect:", dict(Counter((a["cause"], a["effect"]) for a in alerts)))
    print("informed entities:", dict(Counter(k for a in alerts for k in a["informed"])))
    print("with active_period:", sum(1 for a in alerts if a["active_periods"]))
    print("languages:", dict(Counter(tuple(sorted(a["header"])) for a in alerts)))
    if alerts:
        print("first:", {k: (v if k in ("cause", "effect", "informed") else str(v)[:90]) for k, v in alerts[0].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
