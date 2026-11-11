"""Checks for the RSS-to-API conversion and the last-known-status fallback; no network."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import disturbances_feed
from disturbances_feed import FeedError, LastKnownStatus, clean, compare, convert

HERE = Path(__file__).parent
RECORDED = HERE / "results" / "2026-11-11-disturbances-feed-en.xml"

WORKS = "http://www.belgianrail.be/jp/nmbs-realtime/help.exe/en?tpl=showmap_external&amp;tplParamHimMsgInfoGroup=works&amp;messageID=1&amp;"
TROUBLE = WORKS.replace("=works", "=trouble")


def rss(*items: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><channel>'
        "<title>Works</title><pubDate>Wed, 11 Nov 2026 22:48:00 +0100</pubDate>" + "".join(items) + "</channel></rss>"
    )


def item(title: str, description: str, link: str, date: str = "Tue, 10 Nov 2026 16:48:07 +0100") -> str:
    return (
        f"<item><title><![CDATA[{title}]]></title><description><![CDATA[{description}]]></description>"
        f"<link>{link}</link><pubDate>{date}</pubDate></item>"
    )


class ConvertTests(unittest.TestCase):
    def test_planned_item_with_links(self):
        xml = rss(item("A - B", 'Works.<br><br/><a href="https://x.test/faq">More info </a><br/><a href="https://x.test/pdf">Bus</a>', WORKS))
        response = convert(xml)
        self.assertEqual(response["version"], "1.4")
        (one,) = response["disturbance"]
        self.assertEqual(one["id"], "0")
        self.assertEqual(one["type"], "planned")
        self.assertEqual(one["title"], "A - B")
        self.assertEqual(one["description"], "Works.\n\nMore info \nBus")
        self.assertEqual(one["richtext"], one["description"])
        self.assertEqual(one["link"], "https://x.test/faq")  # the first link in the text, not the feed's own link
        self.assertEqual(one["timestamp"], "1794325687")  # 2026-11-10 16:48:07 +01:00
        self.assertEqual(one["descriptionLinks"]["number"], "2")
        self.assertEqual(one["descriptionLinks"]["descriptionLink"][1], {"id": "1", "link": "https://x.test/pdf", "text": "Bus"})

    def test_unplanned_item_without_links_links_to_the_feed_item(self):
        (one,) = convert(rss(item("Brussels", "A train broke down.", TROUBLE)), "nl")["disturbance"]
        self.assertEqual(one["type"], "disturbance")
        self.assertEqual(one["link"], TROUBLE.replace("&amp;", "&"))
        self.assertEqual(one["descriptionLinks"]["descriptionLink"][0]["text"], "Lees meer")

    def test_ids_follow_feed_order_and_empty_feed_is_fine(self):
        response = convert(rss(item("a", "x", WORKS), item("b", "y", TROUBLE)))
        self.assertEqual([d["id"] for d in response["disturbance"]], ["0", "1"])
        self.assertEqual(convert(rss())["disturbance"], [])

    def test_clean(self):
        self.assertEqual(clean("a&nbsp;b".replace("&nbsp;", " ") + "<br>c<br />d <b>e</b>  f"), "a b\nc\nd e f")

    def test_rejects_garbage(self):
        for body in (b"<html>captcha</html>", b"not xml", b""):
            with self.subTest(body=body), self.assertRaises(FeedError):
                convert(body)

    @unittest.skipUnless(RECORDED.exists(), "recorded sample missing")
    def test_recorded_sample_matches_the_api_shape(self):
        response = convert(RECORDED.read_bytes())
        self.assertEqual(len(response["disturbance"]), 48)
        self.assertEqual({d["type"] for d in response["disturbance"]}, {"planned"})
        for entry in response["disturbance"]:
            self.assertEqual(
                set(entry), {"id", "title", "description", "type", "link", "timestamp", "richtext", "descriptionLinks"}
            )
            self.assertEqual(int(entry["descriptionLinks"]["number"]), len(entry["descriptionLinks"]["descriptionLink"]))
        self.assertEqual(compare(response, response), [])


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000.0
        self.status = LastKnownStatus(Path(self.tmp.name), stale_after=3600, clock=lambda: self.now)

    def up(self, lang):
        return rss(item("t", "d", WORKS)).encode()

    def down(self, lang):
        raise FeedError("503")

    def test_fresh_answer_is_not_from_cache(self):
        response, cached = self.status.get("en", self.up)
        self.assertFalse(cached)
        self.assertEqual(len(response["disturbance"]), 1)

    def test_outage_serves_last_known_status(self):
        first, _ = self.status.get("en", self.up)
        self.now += 600
        again, cached = self.status.get("en", self.down)
        self.assertTrue(cached)
        self.assertEqual(again, first)

    def test_captcha_page_counts_as_an_outage(self):
        first, _ = self.status.get("en", self.up)
        again, cached = self.status.get("en", lambda lang: b"<html>captcha</html>")
        self.assertTrue(cached)
        self.assertEqual(again, first)

    def test_too_old_or_missing_or_other_language_raises(self):
        with self.assertRaises(FeedError):
            self.status.get("en", self.down)  # nothing stored yet
        self.status.get("en", self.up)
        with self.assertRaises(FeedError):
            self.status.get("fr", self.down)  # stored for another language only
        self.now += 3601
        with self.assertRaises(FeedError):
            self.status.get("en", self.down)  # stored, but too old to trust

    def test_corrupt_cache_file_raises_instead_of_crashing(self):
        self.status.get("en", self.up)
        (Path(self.tmp.name) / "disturbances-en.json").write_text("{not json")
        with self.assertRaises(FeedError):
            self.status.get("en", self.down)


class CompareTests(unittest.TestCase):
    def test_reports_differences(self):
        a = convert(rss(item("t", "d", WORKS)))
        b = convert(rss(item("t", "other", WORKS)))
        self.assertEqual(compare(a, a), [])
        self.assertTrue(any("description" in line for line in compare(a, b)))
        self.assertTrue(any("count" in line for line in compare(a, convert(rss()))))


if __name__ == "__main__":
    assert disturbances_feed
    unittest.main()
