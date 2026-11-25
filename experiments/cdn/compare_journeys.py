"""Compare CDN journey options with the iRail API and the reference planner (#257, #258).

Run: uv run --locked python experiments/cdn/compare_journeys.py [--pairs 40] [--write report.md]
The reference planner needs Node 22.12+ and `npm install --prefix experiments/cdn/reference`; without it
only the API comparison runs (use --no-reference to skip it explicitly).

Each search runs on every source for the same pair and time. Options are matched by scheduled departure,
scheduled arrival and number of transfers. The report lists the options that only one side returned, with
the vehicles, so that differences can be told apart: international trains the CDN does not publish,
an alternative the other planner chose differently, or a search limit.
"""

import argparse
import asyncio
import json
from datetime import datetime, timedelta
import logging
from pathlib import Path
import random
import shutil
import subprocess
from zoneinfo import ZoneInfo

from aiohttp import ClientSession, ClientTimeout

from pyrail import CdnBackend, IRail
from pyrail.exceptions import NotFoundError, PyRailError

logging.disable(logging.WARNING)

STATIONS = (
    # Busy and remote Belgian stations; names come from the CDN's catalog.
    "008812005",
    "008813003",
    "008814001",
    "008821006",
    "008892007",
    "008891009",
    "008891702",
    "008841004",
    "008833001",
    "008831005",
    "008863008",
    "008863354",
    "008861200",
    "008896008",
    "008883006",
    "008841558",
    "008844628",
    "008866001",
    "008863503",
    "008812021",
    "008821121",
    "008893120",
    "008895000",
    "008844008",
    "008885001",
)
TIMES = ("0630", "0900", "1215", "1730", "2130")
DAY = ZoneInfo("Europe/Brussels")


def _key(connection) -> tuple[str, str, int]:  # noqa: ANN001
    local = connection.departure.time.astimezone(DAY), connection.arrival.time.astimezone(DAY)
    return local[0].strftime("%H:%M"), local[1].strftime("%H:%M"), len(connection.vias or ())


def _size(answer: object) -> str:
    return answer if isinstance(answer, str) else str(len(answer))  # ty: ignore[invalid-argument-type]


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


def _reference(queries: list[dict]) -> list[dict[tuple[str, str, int], str] | str]:
    """Search with @irail/planner; each answer maps option keys to vehicles, or holds an error."""
    folder = Path(__file__).parent / "reference"
    if shutil.which("node") is None or not (folder / "node_modules").exists():
        return ["reference planner not installed"] * len(queries)
    run = subprocess.run(
        ["node", str(folder / "planner.mjs")],  # noqa: S607
        input=json.dumps(queries),
        capture_output=True,
        text=True,
        check=True,
    )
    answers = []
    for answer in json.loads(run.stdout):
        if isinstance(answer, dict):
            answers.append(answer["error"])
            continue
        options = {}
        for option in answer:
            departure = datetime.fromisoformat(option["departure"]).astimezone(DAY).strftime("%H:%M")
            arrival = datetime.fromisoformat(option["arrival"]).astimezone(DAY).strftime("%H:%M")
            options[departure, arrival, option["transfers"]] = option["vehicles"]
        answers.append(options)
    return answers


async def main(args: argparse.Namespace) -> None:
    generator = random.Random(args.seed)
    date = (datetime.now(DAY) + timedelta(days=1)).strftime("%d%m%y")
    pairs = [tuple(generator.sample(STATIONS, 2)) for _ in range(args.pairs)]
    plan = [
        (origin, destination, TIMES[index % len(TIMES)], "arrival" if index % 5 == 4 else "departure")
        for index, (origin, destination) in enumerate(pairs)
    ]
    day = datetime.strptime(date, "%d%m%y").replace(tzinfo=DAY)
    names: dict[str, str] = {}
    reference = (
        [None] * len(plan)
        if args.no_reference
        else _reference(
            [
                {
                    "from": f"BE.NMBS.{origin}",
                    "to": f"BE.NMBS.{destination}",
                    "time": day.replace(hour=int(time[:2]), minute=int(time[2:])).isoformat(),
                    "arriveBy": selection == "arrival",
                }
                for origin, destination, time, selection in plan
            ]
        )
    )
    lines: list[str] = []
    keys = ("searches", "compared", "api", "cdn", "shared", "api_only", "cdn_only", "api_error", "cdn_error")
    totals = {"api": dict.fromkeys(keys, 0), "reference": dict.fromkeys(keys, 0)}
    async with (
        ClientSession(timeout=ClientTimeout(total=60)) as session,
        IRail(backend=CdnBackend(session=session)) as cdn,
        IRail() as api,
    ):
        names.update(
            {station.id.removeprefix("BE.NMBS."): station.name for station in (await cdn.get_stations()).stations}
        )
        for (origin, destination, time, selection), planner in zip(plan, reference, strict=True):
            sources = {
                "api": await _search(api, origin, destination, date, time, selection),
                "reference": planner,
            }
            new = await _search(cdn, origin, destination, date, time, selection)
            label = f"{names.get(origin, origin)} -> {names.get(destination, destination)} {time} ({selection})"
            for name, old in sources.items():
                if old is None:
                    continue
                count = totals[name]
                count["searches"] += 1
                if isinstance(old, str) or isinstance(new, str):
                    count["api_error"] += isinstance(old, str)
                    count["cdn_error"] += isinstance(new, str)
                    lines.append(f"- {label} vs {name}: {name} {_size(old)}, CDN {_size(new)}")
                    continue
                shared, only_old, only_new = old.keys() & new.keys(), old.keys() - new.keys(), new.keys() - old.keys()
                count["compared"] += 1
                count["api"] += len(old)
                count["cdn"] += len(new)
                count["shared"] += len(shared)
                count["api_only"] += len(only_old)
                count["cdn_only"] += len(only_new)
                if only_old or only_new:
                    lines.append(
                        f"- {label} vs {name}: {len(shared)} shared; {name} only "
                        f"{[(key, old[key]) for key in sorted(only_old)]}; "
                        f"CDN only {[(key, new[key]) for key in sorted(only_new)]}"
                    )
    report = [
        "# Journey comparison: CDN backend against the iRail API and the reference planner",
        "",
        f"Measured {datetime.now(DAY).isoformat(timespec='minutes')}, service date {date}, {args.pairs} random pairs "
        f"(seed {args.seed}) from {len(STATIONS)} Belgian stations. Options match on scheduled departure, arrival "
        "and transfers. Columns count options of the other source (`other`), of the CDN, and those they share.",
        "",
        "| Source | Searches | Compared | Other options | CDN options | Shared | Other only | CDN only | Other failed | CDN failed |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *(
            f"| {name} | {c['searches']} | {c['compared']} | {c['api']} | {c['cdn']} | {c['shared']} | "
            f"{c['api_only']} | {c['cdn_only']} | {c['api_error']} | {c['cdn_error']} |"
            for name, c in totals.items()
            if c["searches"]
        ),
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
    parser.add_argument("--no-reference", action="store_true", help="skip the reference planner")
    asyncio.run(main(parser.parse_args()))
