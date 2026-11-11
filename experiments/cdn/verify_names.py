"""Compare station and vehicle names derived from the CDN data with the live iRail API (spike #248).

Two questions that #248 left open:
  1. Which CDN column equals the API's `standardname` (and its per-language `name`)?
  2. Can a vehicle's `name`, `shortname`, `number`, `type`, `@id` (and `locationX/Y`) be derived from the
     `vehicleIri` in `tripEnrichment`, for every train type?

Needs `fetch_data.py DIR` and `inspect_extensions.py DIR` first (the latter downloads DIR/ext/*.arrow).
The vehicle check makes about 2 requests per second to the live API, 5 vehicles per train type.

Run from the repository root: uv run python experiments/cdn/verify_names.py [DIR]
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
import json
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from _common import data_dir
from pyrail.cdn.arrow import read_table

API = "https://api.irail.be/v1"
PER_TYPE = 5
MAX_TRIES = 20  # per type: many CDN vehicles are unknown to the API, so keep trying until PER_TYPE answer
LANGUAGES = ("nl", "fr", "de", "en")


def get(path: str) -> dict:
    """GET a JSON document from the live API, throttled to stay under its rate limit."""
    time.sleep(0.5)
    request = Request(f"{API}/{path}", headers={"User-Agent": "pyrail-experiments"})  # noqa: S310
    with urlopen(request, timeout=60) as response:  # noqa: S310
        return json.loads(response.read())


def stations(data) -> None:
    """Match each CDN station column against the API's `standardname` and per-language `name`."""
    cdn = read_table((data / "ext" / "stations.arrow").read_bytes())
    rows = {iri: i for i, iri in enumerate(cdn["iri"])}
    enrichment = read_table((data / "ext" / "stopEnrichment.arrow").read_bytes())
    enriched = {iri: i for i, iri in enumerate(enrichment["iri"])}

    api = {lang: {s["@id"]: s for s in get(f"stations?format=json&lang={lang}")["station"]} for lang in LANGUAGES}
    ids = api["en"]
    print(f"\n== stations: API {len(ids)}, CDN stations {len(rows)}, CDN stopEnrichment {len(enriched)}")
    print(f"   in API, not in CDN stations: {len(set(ids) - set(rows))}; the other way: {len(set(rows) - set(ids))}")

    def report(label: str, pairs: list[tuple[str, str]]) -> None:
        wrong = [(a, b) for a, b in pairs if a != b]
        print(f"   {label:46} {len(pairs) - len(wrong):4} / {len(pairs)} equal", end="")
        print(f"   e.g. API {wrong[0][0]!r} vs CDN {wrong[0][1]!r}" if wrong else "")

    common = [i for i in ids if i in rows]
    report("standardname == stations.name", [(ids[i]["standardname"], cdn["name"][rows[i]]) for i in common])
    for lang, column in (("nl", "alternativeNl"), ("fr", "alternativeFr"), ("de", "alternativeDe"), ("en", "alternativeEn")):
        pairs = [(api[lang][i]["name"], cdn[column][rows[i]] or cdn["name"][rows[i]]) for i in common]
        report(f"name[{lang}] == stations.{column} or .name", pairs)
        both = [i for i in common if i in enriched]
        pairs = [(api[lang][i]["name"], enrichment[f"name{lang.title()}"][enriched[i]]) for i in both]
        report(f"name[{lang}] == stopEnrichment.name{lang.title()}", pairs)
    pairs = [(ids[i]["standardname"], enrichment["nameNl"][enriched[i]]) for i in common if i in enriched]
    report("standardname == stopEnrichment.nameNl", pairs)
    pairs = [(ids[i]["standardname"], enrichment["nameFr"][enriched[i]]) for i in common if i in enriched]
    report("standardname == stopEnrichment.nameFr", pairs)
    pairs = [(float(ids[i]["locationX"]), float(cdn["lon"][rows[i]])) for i in common]
    print(f"   longitude within 1e-4: {sum(abs(a - b) < 1e-4 for a, b in pairs)} / {len(pairs)}")
    pairs = [(float(ids[i]["locationY"]), float(cdn["lat"][rows[i]])) for i in common]
    print(f"   latitude within 1e-4:  {sum(abs(a - b) < 1e-4 for a, b in pairs)} / {len(pairs)}")
    ids_ok = sum(i.rsplit("/", 1)[1] and ids[i]["id"] == "BE.NMBS." + i.rsplit("/", 1)[1] for i in ids)
    print(f"   `id` == 'BE.NMBS.' + number from the IRI: {ids_ok} / {len(ids)}")


def derive(iri: str) -> dict[str, str]:
    """The rule under test: split the IRI's last segment into letters and digits."""
    tail = iri.rsplit("/", 1)[1]
    match = re.fullmatch(r"([A-Za-z]+)(\d+)", tail)
    if not match:
        return {"@id": iri, "name": "BE.NMBS." + tail}
    kind, number = match.groups()
    if kind == "S":  # S lines: the train number is the last four digits (S102056 is line S10, train 2056)
        kind, number = kind + number[:-4], number[-4:]
    return {"@id": iri, "name": "BE.NMBS." + tail, "shortname": f"{kind} {number}", "number": number, "type": kind}


def vehicles(data) -> None:
    """Check the derivation against the API for a few vehicles of every type that runs tomorrow."""
    trips = read_table((data / "ext" / "tripEnrichment.arrow").read_bytes())
    by_type: dict[str, list[str]] = defaultdict(list)
    for iri in sorted(set(trips["vehicleIri"])):
        by_type[re.match(r"[A-Za-z]+", iri.rsplit("/", 1)[1]).group()].append(iri)  # type: ignore[union-attr]
    unmatched = [iri for iri in set(trips["vehicleIri"]) if not re.fullmatch(r"[A-Za-z]+\d+", iri.rsplit("/", 1)[1])]
    print(f"\n== vehicles: {sum(map(len, by_type.values()))} distinct vehicle IRIs, {len(unmatched)} do not match letters+digits")
    print(f"   non-matching examples: {unmatched[:5]}")

    day = (datetime.now(UTC) + timedelta(days=1)).strftime("%d%m%y")
    fields = ("name", "shortname", "number", "type", "@id")
    results: dict[str, Counter] = {}
    examples: dict[str, list[str]] = defaultdict(list)
    for kind, iris in sorted(by_type.items()):
        # Spread the sample over the numbers instead of taking the first few.
        counts: Counter = Counter()
        step = max(len(iris) // MAX_TRIES, 1)
        for iri in iris[::step][:MAX_TRIES]:
            if counts["checked"] >= PER_TYPE:
                break
            tail = iri.rsplit("/", 1)[1]
            try:
                reply = get(f"vehicle?id=BE.NMBS.{tail}&format=json&lang=en&date={day}")
            except HTTPError as error:
                counts[f"http {error.code}"] += 1
                continue
            info = reply["vehicleinfo"]
            if info["@id"] != iri:  # the API matched another vehicle (by number): not a comparison
                counts["resolved elsewhere"] += 1
                examples[kind].append(f"{tail}: API answered with {info['@id']}")
                continue
            counts["checked"] += 1
            for field in fields:
                if derive(iri).get(field) == info.get(field):
                    counts[field] += 1
                else:
                    examples[kind].append(f"{tail}: {field} API {info.get(field)!r} vs derived {derive(iri).get(field)!r}")
            first = reply["stops"]["stop"][0]["stationinfo"]
            counts["xy_first_stop"] += (info["locationX"], info["locationY"]) == (first["locationX"], first["locationY"])
            counts["xy_zero"] += info["locationX"] == "0" and info["locationY"] == "0"
        results[kind] = counts
    print(f"   {'type':5} {'checked':>7} " + " ".join(f"{f:>9}" for f in fields) + "  xy=first  xy=0   other")
    for kind, counts in results.items():
        other = {k: v for k, v in counts.items() if k.startswith("http") or k == "resolved elsewhere"}
        print(f"   {kind:5} {counts['checked']:7} " + " ".join(f"{counts[f]:9}" for f in fields) + f" {counts['xy_first_stop']:9} {counts['xy_zero']:5}   {other or ''}")
    for kind, lines in examples.items():
        print(f"   mismatches for {kind}: {lines[:4]}")


if __name__ == "__main__":
    directory = data_dir()
    stations(directory)
    vehicles(directory)
