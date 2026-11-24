"""Compare CDN and iRail API journey options over many station pairs (#257, #258).

Run: uv run --locked python experiments/cdn/compare_journeys.py [--pairs 40] [--write report.md]

Each search runs on both backends for the same pair and time. Options are matched by scheduled departure,
scheduled arrival and number of transfers. The report lists the options that only one side returned and
classifies them: a different journey for the same departure (the CDN found a faster or slower one), or
an option absent altogether (later than the other side's last option, or a different planner choice).
"""

import argparse
import asyncio
from datetime import datetime, timedelta
import logging
from pathlib import Path
import random
from zoneinfo import ZoneInfo

from aiohttp import ClientSession, ClientTimeout

from pyrail import CdnBackend, IRail
from pyrail.exceptions import NotFoundError, PyRailError

logging.disable(logging.WARNING)

STATIONS = {
    "008812005": "Brussels-North",
    "008813003": "Brussels-Central",
    "008814001": "Brussels-South",
    "008821006": "Antwerpen-Centraal",
    "008892007": "Gent-Sint-Pieters",
    "008891009": "Brugge",
    "008891702": "Oostende",
    "008841004": "Liege-Guillemins",
    "008833001": "Leuven",
    "008831005": "Mechelen",
    "008863008": "Namur",
    "008863354": "Charleroi-Central",
    "008861200": "Mons",
    "008896008": "Kortrijk",
    "008883006": "Hasselt",
    "008841558": "Verviers-Central",
    "008844628": "Eupen",
    "008866001": "Arlon",
    "008863503": "Dinant",
    "008812021": "Schaerbeek",
    "008821121": "Berchem",
    "008893120": "Aalst",
    "008895000": "Sint-Niklaas",
    "008844008": "Welkenraedt",
    "008885001": "Genk",
    "008831757": "Aarschot",
}
TIMES = ("0630", "0900", "1215", "1730", "2130")
DAY = ZoneInfo("Europe/Brussels")


def _key(connection) -> tuple[str, str, int]:  # noqa: ANN001
    local = connection.departure.time.astimezone(DAY), connection.arrival.time.astimezone(DAY)
    return local[0].strftime("%H:%M"), local[1].strftime("%H:%M"), len(connection.vias or ())


def _vehicles(connection) -> str:  # noqa: ANN001
    legs = [connection.departure.vehicle_info.short_name]
    legs += [via.departure.vehicle_info.short_name for via in connection.vias or ()]
    return " > ".join(legs)


async def _search(client: IRail, origin: str, destination: str, date: str, time: str, selection: str):  # noqa: ANN202
    try:
        response = await client.get_connections(
            f"BE.NMBS.{origin}", f"BE.NMBS.{destination}", date, time, timesel=selection
        )
    except (NotFoundError, PyRailError) as error:
        return type(error).__name__
    return {_key(connection): _vehicles(connection) for connection in response.connections or ()}


async def main(args: argparse.Namespace) -> None:
    generator = random.Random(args.seed)
    date = (datetime.now(DAY) + timedelta(days=1)).strftime("%d%m%y")
    pairs = [tuple(generator.sample(sorted(STATIONS), 2)) for _ in range(args.pairs)]
    lines = []
    totals = dict.fromkeys(("searches", "api", "cdn", "shared", "api_only", "cdn_only", "api_error", "cdn_error"), 0)
    api_only_after = 0
    async with (
        ClientSession(timeout=ClientTimeout(total=60)) as session,
        IRail(backend=CdnBackend(session=session)) as cdn,
        IRail() as api,
    ):
        for index, (origin, destination) in enumerate(pairs):
            time = TIMES[index % len(TIMES)]
            selection = "arrival" if index % 5 == 4 else "departure"
            old = await _search(api, origin, destination, date, time, selection)
            new = await _search(cdn, origin, destination, date, time, selection)
            totals["searches"] += 1
            label = f"{STATIONS[origin]} -> {STATIONS[destination]} {time} ({selection})"
            if isinstance(old, str) or isinstance(new, str):
                totals["api_error"] += isinstance(old, str)
                totals["cdn_error"] += isinstance(new, str)
                lines.append(f"- {label}: API {old if isinstance(old, str) else len(old)}, CDN {new if isinstance(new, str) else len(new)}")
                continue
            shared, only_api, only_cdn = old.keys() & new.keys(), old.keys() - new.keys(), new.keys() - old.keys()
            totals["api"] += len(old)
            totals["cdn"] += len(new)
            totals["shared"] += len(shared)
            totals["api_only"] += len(only_api)
            totals["cdn_only"] += len(only_cdn)
            if only_api or only_cdn:
                last_cdn = max((arrival for _, arrival, _ in new), default="")
                api_only_after += sum(1 for dep, _, _ in only_api if dep > min((d for d, _, _ in new), default="99"))
                lines.append(
                    f"- {label}: {len(shared)} shared; API only {[(key, old[key]) for key in sorted(only_api)]}; "
                    f"CDN only {[(key, new[key]) for key in sorted(only_cdn)]} "
                    f"(last CDN arrival {last_cdn})"
                )
    report = [
        "# Journey comparison: CDN backend against the iRail API",
        "",
        f"Measured {datetime.now(DAY).isoformat(timespec='minutes')}, service date {date}, {args.pairs} random pairs "
        f"(seed {args.seed}) from {len(STATIONS)} Belgian stations.",
        "",
        "| Measure | Count |",
        "|---|---|",
        *(f"| {key.replace('_', ' ')} | {value} |" for key, value in totals.items()),
        "",
        "Differences (searches where every option matched are not listed):",
        "",
        *(lines or ["- none"]),
    ]
    text = "\n".join(report)
    print(text)
    if args.write:
        Path(args.write).write_text(text + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=40)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--write")
    asyncio.run(main(parser.parse_args()))
