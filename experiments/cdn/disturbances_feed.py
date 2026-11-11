"""Rebuild the iRail `/disturbances` response from the NMBS/SNCB RSS feed (spike #263).

iRail's own server (`NmbsRssDisturbancesClient` in iRail/iRail) fetches the URL below over plain HTTP; HTTPS
answers with the same document, so this script uses HTTPS:

    https://www.belgianrail.be/jp/sncb-nmbs-routeplanner/help.exe/{nl|fr|de|en}?tpl=rss_feed

and converts every RSS `<item>` into one disturbance. This script does the same with the standard library only,
keeps the last good answer on disk for outages, and can compare the result with the live API.

    uv run python experiments/cdn/disturbances_feed.py [LANG]            # print the rebuilt response (JSON)
    uv run python experiments/cdn/disturbances_feed.py [LANG] --compare  # diff against api.irail.be

Findings are in results/2026-11-11-disturbances.md.
"""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from xml.etree import ElementTree

FEED = "https://www.belgianrail.be/jp/sncb-nmbs-routeplanner/help.exe/{lang}?tpl=rss_feed"
API = "https://api.irail.be/disturbances/?format=json&lang={lang}"
USER_AGENT = "pyrail-experiments"
LANGUAGES = ("nl", "fr", "de", "en")
READ_MORE = {"nl": "Lees meer", "fr": "Lire plus", "en": "Read more", "de": "Weiterlesen"}  # iRail's wording
STALE_AFTER = 12 * 3600  # iRail keeps its backup answer for 12 hours; so do we

_LINK = re.compile(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>')
_BREAK = re.compile(r"<br\s*/?>")
_TAG = re.compile(r"<[^>]*>")
_SPACE = re.compile(r"[^\S\n]+")


class FeedError(Exception):
    """The feed could not be fetched or is not an RSS document."""


def clean(html: str) -> str:
    """Turn the feed's HTML fragment into the API's plain text: `<br>` becomes a newline, other tags go.

    Runs of spaces collapse to one, but a space before a newline stays: the API keeps it too.
    """
    html = _BREAK.sub("\n", html.replace(" ", " "))
    return _SPACE.sub(" ", _TAG.sub("", html)).strip()


def convert(xml: bytes | str, lang: str = "en") -> dict:
    """Convert the RSS document to the API's response shape (`DisturbancesApiResponse.from_dict` input)."""
    try:
        root = ElementTree.fromstring(xml)  # noqa: S314 - plain RSS from the operator, no DTD/entities in use
    except ElementTree.ParseError as err:
        msg = f"not valid XML: {err}"
        raise FeedError(msg) from err
    if root.tag != "rss":
        msg = f"expected <rss>, got <{root.tag}>"
        raise FeedError(msg)

    disturbances = []
    for index, item in enumerate(root.iterfind("./channel/item")):
        title = (item.findtext("title") or "").strip()
        description = item.findtext("description") or ""
        item_link = (item.findtext("link") or "").strip()
        published = parsedate_to_datetime(item.findtext("pubDate") or "")

        links = [{"id": str(i), "link": url, "text": text} for i, (url, text) in enumerate(_LINK.findall(description))]
        if not links:  # an item without links of its own gets a "read more" pointing at the feed's link
            links = [{"id": "0", "link": item_link, "text": READ_MORE.get(lang, "Read more")}]
        text = clean(description)
        disturbances.append(
            {
                "id": str(index),  # the API's id is just the position in the list
                "title": title,
                "description": text,
                # works (planned) versus trouble (unplanned) is encoded in the item's link
                "type": "planned" if "tplParamHimMsgInfoGroup=works" in item_link else "disturbance",
                "link": links[0]["link"],
                "timestamp": str(int(published.timestamp())),
                "richtext": text,  # the live API returns the same text here
                "descriptionLinks": {"number": str(len(links)), "descriptionLink": links},
            }
        )

    channel_date = root.findtext("./channel/pubDate")
    stamp = parsedate_to_datetime(channel_date) if channel_date else datetime.now(UTC)
    return {"version": "1.4", "timestamp": str(int(stamp.timestamp())), "disturbance": disturbances}


def fetch(lang: str = "en", timeout: float = 20) -> bytes:
    """GET the feed. Raises `FeedError` on any network or HTTP problem."""
    request = Request(FEED.format(lang=lang), headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.read()
    except OSError as err:  # URLError, HTTPError and timeouts are all OSError subclasses
        msg = f"cannot fetch the feed: {err}"
        raise FeedError(msg) from err


class LastKnownStatus:
    """Return fresh data when the feed answers, the last good answer when it does not.

    The cache file is replaced atomically, so a crash never leaves half a document. An answer older than
    `stale_after` seconds is not served: an old "there is a disruption" is worse than an error.
    """

    def __init__(self, directory: Path, stale_after: float = STALE_AFTER, clock=time.time) -> None:
        self.directory = directory
        self.stale_after = stale_after
        self.clock = clock

    def get(self, lang: str = "en", fetcher=fetch) -> tuple[dict, bool]:
        """Return `(response, from_cache)`. Raises `FeedError` if the feed is down and nothing usable is cached."""
        path = self.directory / f"disturbances-{lang}.json"
        try:
            response = convert(fetcher(lang), lang)
        except FeedError:
            cached = self._read(path)
            if cached is None:
                raise
            return cached, True
        self._write(path, response)
        return response, False

    def _read(self, path: Path) -> dict | None:
        try:
            entry = json.loads(path.read_text())
            if self.clock() - entry["stored"] > self.stale_after:
                return None
            return entry["response"]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write(self, path: Path, response: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        with os.fdopen(fd, "w") as file:
            json.dump({"stored": self.clock(), "response": response}, file)
        Path(tmp).replace(path)


def compare(rebuilt: dict, live: dict) -> list[str]:
    """List every difference between the rebuilt response and the API's, ignoring the volatile top-level stamp."""
    problems = []
    ours, theirs = rebuilt["disturbance"], live["disturbance"]
    if len(ours) != len(theirs):
        problems.append(f"count: rebuilt {len(ours)}, API {len(theirs)}")
    if rebuilt["version"] != live["version"]:
        problems.append(f"version: rebuilt {rebuilt['version']!r}, API {live['version']!r}")
    for mine, other in zip(ours, theirs, strict=False):
        for key in sorted(set(mine) | set(other)):
            if mine.get(key) != other.get(key):
                problems.append(f"#{other.get('id')} {key}: rebuilt {str(mine.get(key))[:80]!r}, API {str(other.get(key))[:80]!r}")
    return problems


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    lang = args[0] if args else "en"
    if lang not in LANGUAGES:
        print(f"language must be one of {LANGUAGES}", file=sys.stderr)
        return 2
    rebuilt = convert(fetch(lang), lang)
    if "--compare" not in argv:
        print(json.dumps(rebuilt, ensure_ascii=False, indent=2))
        return 0
    request = Request(API.format(lang=lang), headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urlopen(request, timeout=30) as response:  # noqa: S310
        live = json.loads(response.read())
    problems = compare(rebuilt, live)
    print(f"{lang}: rebuilt {len(rebuilt['disturbance'])}, API {len(live['disturbance'])}, differences {len(problems)}")
    for line in problems[:40]:
        print("  ", line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
