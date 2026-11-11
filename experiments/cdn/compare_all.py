"""Compare every explored library on the same data and write the results as Markdown.

Run from the repository root:
  python experiments/cdn/fetch_data.py data --date 2026-11-12 --pages 8
  uv run --group experiments python experiments/cdn/compare_all.py data --write experiments/cdn/results/2026-11-11.md

Each reader runs in its own process (bench_readers.py), so peak memory is not shared. Values returned by every
reader that can open the files must be identical to pyarrow's, or the run exits with an error.
"""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from _common import data_dir, files, version

HERE = Path(__file__).parent
READERS = [
    ("stdlib", "pyrail.cdn.arrow.read_table (standard library)", "pyrail"),
    ("pyarrow", "pyarrow", "pyarrow"),
    ("arro3", "arro3-io", "arro3-io"),
    ("nanoarrow", "nanoarrow", "nanoarrow"),
]


def run(script: str, *args: str) -> dict:
    process = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True, check=False)  # noqa: S603
    if process.returncode:
        raise SystemExit(f"{script} failed:\n{process.stderr}")
    return json.loads(process.stdout.strip().splitlines()[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dir", nargs="?", default="data")
    parser.add_argument("--write", type=Path, help="also write the report to this Markdown file")
    args = parser.parse_args()
    data = data_dir([args.dir])

    results = {name: run("bench_readers.py", name, str(data)) for name, _, _ in READERS}
    realtime = run("bench_realtime.py", str(data))
    reference = results["pyarrow"].get("digest")
    mismatched = [n for n, r in results.items() if r.get("digest") and r["digest"] != reference]

    manifest = json.loads((data / "manifest.jsonld").read_text())
    pages = len(list((data / "pages").glob("p*.arrow")))
    lines = [
        f"# CDN reader comparison, {datetime.now(UTC).date()}",
        "",
        f"- Release `{manifest['releaseId']}` (coverage {manifest['coverageStart'][:10]} to {manifest['coverageEnd'][:10]}).",
        f"- Data: {len(files(data))} files = 4 tables + {pages} consecutive connection pages; every column of every file is decoded into Python lists.",
        f"- Machine: {platform.machine()}, {os.cpu_count()} CPUs, Python {platform.python_version()}, {platform.system()} {platform.release()}. "
        "**Not a Raspberry Pi or other Home Assistant-class device.**",
        "- Time: best and median of 3 passes in one process. Peak RSS is the process peak (one pass held in memory at a time), with its value before reading in brackets (the stdlib reader imports `pyrail`, which loads aiohttp).",
        "- Installed size: files of the distribution(s) in this environment; `stdlib` adds nothing.",
        "",
        "## Readers",
        "",
        "| Reader | Version | Rows | Time best / median | Peak RSS (before) | Installed | Same values as pyarrow |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, label, distribution in READERS:
        r = results[name]
        shown = "in repo" if name == "stdlib" else version(distribution)
        installed = "none" if name == "stdlib" else f"{r['installed_mb']} MB"
        if "error" in r:
            lines.append(f"| {label} | {shown} | | **cannot read the files** | | {installed} | |")
        else:
            same = "yes" if r["digest"] == reference else "**NO**"
            lines.append(
                f"| {label} | {shown} | {r['rows']} | {r['ms_best']} / {r['ms_median']} ms | "
                f"{r['rss_peak_mb']} ({r['rss_start_mb']}) MB | {installed} | {same} |"
            )
    errors = [f"- {label}: `{results[name]['error']}`" for name, label, _ in READERS if "error" in results[name]]
    if errors:
        lines += ["", "Why a reader failed:", "", *errors, "", "The CDN files have no Schema message before the record batches (see `check_schema_message.py`); the same table written as an IPC stream is readable (see `probe_nanoarrow.py`)."]
    lines += [
        "",
        "## GTFS Realtime snapshot",
        "",
        f"`gtfs-realtime-bindings` {version('gtfs-realtime-bindings')} + `protobuf` {version('protobuf')} "
        f"({realtime['installed_mb']} MB installed): {realtime['bytes']} bytes, {realtime['entities']} trip entities, "
        f"parsed in {realtime['ms_best']} ms (best of 5), peak RSS {realtime['rss_peak_mb']} MB. "
        f"Stop ids carry the platform as a suffix, e.g. `{realtime['example_stop_ids'][0]}`.",
        "",
        "## Not covered",
        "",
        "Raspberry Pi measurements, GitHub activity and download counts of the libraries, and memory for a realistic route-planning query (#261). Single-run figures: treat differences of a few milliseconds or megabytes as noise.",
        "",
    ]
    report = "\n".join(lines)
    print(report)
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(report)
    if mismatched:
        raise SystemExit(f"values differ from pyarrow for: {', '.join(mismatched)}")


main()
