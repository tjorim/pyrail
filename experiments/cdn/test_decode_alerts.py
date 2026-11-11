"""Checks for the alerts decoder; the protobuf parts are skipped when gtfs-realtime-bindings is not installed."""

from importlib.util import find_spec
from pathlib import Path
import unittest

import decode_alerts
from decode_alerts import collapse, compare, kind, message_id

RECORDED = Path(__file__).parent / "results" / "2026-11-11-alerts.pb"
HAS_BINDINGS = find_spec("google") is not None and find_spec("google.transit") is not None
URL = "http://www.belgianrail.be/jp/nmbs-realtime/help.exe/en?tpl=showmap_external&tplParamHimMsgInfoGroup={}&messageID=115154&channelFilter=rss_line_90&"


def alert(title="A - B", description="Bus  replaces\ntrains.", group="works"):
    return {
        "entity_id": "rs:nmbssncb:1",
        "cause": "CONSTRUCTION",
        "effect": "NO_SERVICE",
        "active_periods": 0,
        "informed": ["agency"],
        "header": {"en": title},
        "description": {"en": description},
        "url": {"en": URL.format(group)},
    }


class HelperTests(unittest.TestCase):
    def test_message_id_and_kind(self):
        self.assertEqual(message_id(alert()), "115154")
        self.assertEqual(kind(alert(group="works")), "planned")
        self.assertEqual(kind(alert(group="trouble")), "disturbance")
        self.assertIsNone(message_id({"url": {"en": "https://example.test/"}}))

    def test_collapse(self):
        self.assertEqual(collapse(" a \n\n b  c "), "a b c")

    def test_compare_matches_despite_line_breaks_and_reports_the_rest(self):
        rss = {"disturbance": [{"id": "0", "title": "A - B", "description": "Bus replaces \n\ntrains.", "type": "planned"}]}
        self.assertEqual(compare({"alerts": [alert()]}, rss, "en"), [])
        problems = compare({"alerts": [alert(group="trouble")]}, rss, "en")
        self.assertEqual(len(problems), 2)  # the same item, but with another type: one on each side
        self.assertEqual(len(compare({"alerts": []}, rss, "en")), 1)


@unittest.skipUnless(HAS_BINDINGS and RECORDED.exists(), "needs gtfs-realtime-bindings and the recorded sample")
class RecordedSampleTests(unittest.TestCase):
    def test_decodes_the_recorded_feed(self):
        decoded = decode_alerts.decode(RECORDED.read_bytes())
        alerts = decoded["alerts"]
        self.assertEqual(len(alerts), 48)
        self.assertEqual({tuple(sorted(a["header"])) for a in alerts}, {("de", "en", "fr", "nl")})
        self.assertEqual({k for a in alerts for k in a["informed"]}, {"agency"})  # no route, stop or trip scope
        self.assertEqual(sum(a["active_periods"] for a in alerts), 0)  # and no validity period
        self.assertEqual(len({message_id(a) for a in alerts}), 48)
        self.assertEqual({kind(a) for a in alerts}, {"planned"})


if __name__ == "__main__":
    unittest.main()
