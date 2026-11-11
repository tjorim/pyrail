"""Render the dated benchmark JSON files in results/ as one self-contained HTML report (no dependencies).

Run: python experiments/cdn/report_html.py [RESULTS_DIR] [OUTPUT.html]

Each chart uses a log axis (values span microseconds to seconds), labels every bar with its value, and is
followed by a table with the same numbers. Bars are grouped by what is being compared, not by run, so read
the notes: the runs happened at different times on one x86_64 machine (except the Yellow charts) and are not a latency guarantee.
"""

import html
import json
import math
from pathlib import Path
import re
import sys

PREFIX = "2026-11-11-fedora-"


def load(results: Path, name: str):
    return json.loads((results / f"{PREFIX}{name}.json").read_text())


def fmt(ms: float) -> str:
    if ms < 0.1:
        return f"{ms * 1000:.1f} µs"
    if ms < 1000:
        return f"{ms:.3g} ms" if ms < 10 else f"{ms:.0f} ms"
    return f"{ms / 1000:.2f} s"


def bar_chart(rows, title: str, note: str, highlight: int | None = None, unit: str = "ms") -> str:
    """rows: (label, value). Horizontal bars with a data table below.

    Time ("ms") uses a log axis. Memory ("MB") uses a linear axis from zero, since its values are close together.
    """
    linear = unit == "MB"
    if linear:
        lo, hi = 0, math.ceil(max(v for _, v in rows) / 50) * 50
        fmt_value = lambda v: f"{v:.0f} MB"  # noqa: E731
    else:
        lo = 10 ** math.floor(math.log10(min(v for _, v in rows)))
        hi = 10 ** math.ceil(math.log10(max(v for _, v in rows)))
        fmt_value = fmt
    left, width, bar_h, gap = 250, 520, 22, 12
    height = len(rows) * (bar_h + gap) + 34
    if linear:
        scale = lambda v: left + width * v / hi  # noqa: E731
    else:
        scale = lambda v: left + width * (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))  # noqa: E731
    out = [f'<svg viewBox="0 0 {left + width + 90} {height}" role="img" aria-label="{html.escape(title)}">']
    tick = lo
    while tick <= hi * 1.001:
        x = scale(tick) if (linear or tick > 0) else left
        out.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{height - 24}"/>')
        out.append(f'<text class="tick" x="{x:.1f}" y="{height - 8}" text-anchor="middle">{fmt_value(tick)}</text>')
        tick = tick + 50 if linear else tick * 10
    for i, (label, value) in enumerate(rows):
        y = i * (bar_h + gap) + 4
        x2 = scale(value)
        cls = "bar hl" if i == highlight else "bar"
        out.append(f'<text class="label" x="{left - 10}" y="{y + bar_h / 2 + 4}" text-anchor="end">{html.escape(label)}</text>')
        out.append(f'<path class="{cls}" d="M{left},{y} H{x2 - 4:.1f} a4,4 0 0 1 4,4 v{bar_h - 8} a4,4 0 0 1 -4,4 H{left} Z"><title>{html.escape(label)}: {fmt_value(value)}</title></path>')
        out.append(f'<text class="value" x="{x2 + 8:.1f}" y="{y + bar_h / 2 + 4}">{fmt_value(value)}</text>')
    out.append("</svg>")
    table = "".join(f"<tr><td>{html.escape(l)}</td><td>{v:.4g}</td></tr>" for l, v in rows)
    return (
        f"<section><h2>{html.escape(title)}</h2><p class=note>{note}</p>{''.join(out)}"
        f"<details><summary>Table view</summary><table><tr><th>Case</th><th>Value ({unit})</th></tr>{table}</table></details></section>"
    )


def readers(results: Path):
    """Parse the reader table of the dated Markdown report: (label, median ms, peak RSS MB) per working reader."""
    rows = []
    for line in (results / f"{PREFIX}readers.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 7 and " / " in cells[3] and cells[3].endswith(" ms"):
            label = cells[0].replace(" (standard library)", "").replace("pyrail.cdn.arrow.read_table", "pyrail (stdlib)")
            rows.append((label, float(cells[3].split(" / ")[1].split()[0]), float(cells[4].split()[0])))
    return rows


def device_comparison(results: Path):
    """Compare the 12-file reader run on x86_64 with the Home Assistant Yellow run of the same files.

    Returns (time rows, memory rows, realtime rows), each as (label, value) with the median for readers.
    Both come from the dated Markdown reports: the x86_64 run and the Yellow run. Empty lists if either is missing.
    """
    x86_file, yellow_file = results / "2026-11-11.md", results / "2026-11-11-yellow.md"
    if not (x86_file.exists() and yellow_file.exists()):
        return [], [], []
    short = {"pyrail.cdn.arrow.read_table (standard library)": "pyrail (stdlib)", "pyrail.cdn.arrow.read_table (stdlib)": "pyrail (stdlib)"}
    x86 = {}
    for line in x86_file.read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 7 and cells[3].endswith(" ms") and " / " in cells[3]:
            x86[short.get(cells[0], cells[0])] = (float(cells[3].split(" / ")[1].split()[0]), float(cells[4].split()[0]))
    yellow, realtime = {}, []
    for line in yellow_file.read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        name = short.get(cells[0], re.sub(r" \d[\d.]*$", "", cells[0]))  # drop the version, as "pyarrow 26.0.1"
        if name in x86 and len(cells) == 6 and cells[1].endswith(" ms") and " / " in cells[1]:
            yellow[name] = (float(cells[1].split(" / ")[1].split()[0]), float(cells[2].split()[0]))
        match = re.search(r"\*\*[\d.]+ / ([\d.]+) ms\*\*", line)
        if match and len(cells) == 5:
            label = "Home Assistant core (upb, C)" if "upb" in cells[1] else "Plain pip install (pure Python)"
            realtime.append((f"Realtime snapshot, {label}", float(match.group(1))))
    names = [n for n in x86 if n in yellow]
    times = [row for n in names for row in ((f"{n}, Yellow", yellow[n][0]), (f"{n}, x86_64", x86[n][0]))]
    memory = [row for n in names for row in ((f"{n}, Yellow", yellow[n][1]), (f"{n}, x86_64", x86[n][1]))]
    return times, memory, realtime


def build(results: Path) -> str:
    event = load(results, "event-invalidation")
    short = event["results"][0]["queries"][0]
    queries = [
        ("Per-query validation, result hit", short["validated_hit"]["median_ms"]),
        ("First query after a publication (miss)", short["event_initial_miss"]["median_ms"]),
        ("Event-owned snapshot, result hit", short["event_hit"]["median_ms"]),
    ]
    prepared = load(results, "prepared-cache")["results"]
    layers = {"uncached": "No cache", "memory": "Decoded-table cache", "prepared": "Prepared-window cache"}
    window = [
        (f"{layers[r['mode']]}, {r['hours']} h", r["raw_load_median_ms"] + r["prepare_median_ms"])
        for r in prepared
        if r["hours"] == 24
    ]
    window += [
        (f"{layers[r['mode']]}, {r['hours']} h", r["raw_load_median_ms"] + r["prepare_median_ms"])
        for r in prepared
        if r["hours"] == 48 and r["mode"] != "memory"
    ]
    pooled = load(results, "pooled-downloader")["median_ms"]
    unchanged = load(results, "unchanged-files")["median_ms"]
    refresh = [
        ("urllib, 1 connection, revalidate", pooled["urllib-1"]),
        ("aiohttp, 1 connection, revalidate", pooled["aiohttp-1"]),
        ("aiohttp, 4 connections, revalidate", pooled["aiohttp-4"]),
        ("aiohttp, 4, freshness, rewrite files", unchanged["aiohttp-4-freshness-rewrite"]),
        ("aiohttp, 4, freshness, skip unchanged", unchanged["aiohttp-4-freshness-skip-writes"]),
    ]
    reader_rows = readers(results)
    planner = load(results, "planner")["windows"]
    python = {w["hours"]: w for w in planner if w["storage"] == "python-tuples"}
    scans = [
        (f"{name}, {hours} h window, {label}", w["queries"][i][key]["median_ms"])
        for hours, w in python.items()
        for name, i in (("short", 0), ("long", 1))
        for label, key in (("early stop", "early_stop"), ("full scan", "full_scan"))
    ]
    profile = [
        (f"{q['query']}, {hours} h, {q['profile_scans']} scans", q["profile"]["median_ms"])
        for hours, w in python.items()
        for q in w["queries"]
        if "profile" in q
    ]
    memory = [
        (f"{w['storage'].replace('python-tuples', 'Python tuples').replace('numpy-int64', 'NumPy int64')}, {w['hours']} h", w["rss_peak_mb"])
        for w in planner
    ]
    device_time, device_memory, realtime = device_comparison(results)
    sections = []
    if device_time:
        sections += [
            bar_chart(
                device_time,
                "Reading 12 CDN files (133k rows): Home Assistant Yellow versus x86_64",
                "Median of three passes. The Yellow is a Raspberry Pi CM4 running Home Assistant OS under normal load, about 5 to 9 times slower than the x86_64 machine, with the same ranking.",
                highlight=0,
            ),
            bar_chart(
                device_memory,
                "Peak memory reading the same 12 files, Yellow versus x86_64",
                "Process peak RSS, one pass held in memory. Memory barely depends on the device; the readers rank the same way.",
                highlight=0,
                unit="MB",
            ),
            bar_chart(
                realtime,
                "Parsing the GTFS Realtime snapshot (77 KB) on the Yellow",
                "Home Assistant core ships protobuf with the C upb implementation; a plain pip install on musl aarch64 gets the pure-Python wheel.",
                highlight=0,
            ),
        ]
    sections += [
        bar_chart(
            refresh,
            "Refreshing a 12-page sample from a warm disk cache",
            "Each step changes one thing. The last two rows come from a separate run and trust the cache's freshness lifetime instead of revalidating. HTTP latency to the CDN is part of the first three rows.",
            highlight=4,
        ),
        bar_chart(
            window,
            "Making a 24 h / 48 h connection window ready (load + prepare)",
            "Median of three passes in fresh processes. Prepared windows are reused as they are, so the cost drops to well under a millisecond.",
            highlight=len(window) - 1,
        ),
        bar_chart(
            queries,
            "Repeated earliest-arrival query, Brussels-South to Antwerpen-Centraal (24 h window)",
            "Median of twenty warm samples. Event-owned hits read the published snapshot without checking files; the miss is the first query after every publication.",
            highlight=2,
        ),
        bar_chart(
            [(label, ms) for label, ms, _ in reader_rows],
            "Reading 16 CDN files (162k rows) into Python lists",
            "Best of three passes in one process. nanoarrow cannot open these files (no leading Schema message), so it is not shown.",
            highlight=0,
        ),
        bar_chart(
            [(label, rss) for label, _, rss in reader_rows],
            "Peak memory while reading the same files",
            "Process peak RSS with one pass held in memory. It includes the interpreter and, for the stdlib reader, aiohttp loaded by importing pyrail.",
            highlight=0,
            unit="MB",
        ),
        bar_chart(
            scans,
            "Earliest-arrival scan by window and query (plain Python)",
            "Stopping at the first arrival keeps a search at a few milliseconds; a full scan of the window is the cost of an unreachable target.",
            highlight=0,
        ),
        bar_chart(
            profile,
            "Departure-profile baseline: one scan per possible source departure",
            "Several alternatives are far more expensive than one search. This is the naive baseline, not an optimised profile scan.",
        ),
        bar_chart(
            memory,
            "Peak memory of one prepared window",
            "Process peak RSS in a fresh process, shared by decoded pages, the sorted window and the scans. NumPy storage did not speed up the Python scan here.",
            unit="MB",
        ),
    ]
    meta = f"{html.escape(event['platform'])} · Python {event['python']} · release {html.escape(event['release'])}"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CDN benchmark report</title>
<style>
:root {{ --bg:#fff; --fg:#1b1f24; --muted:#5b6570; --grid:#e3e7ec; --bar:#7aa2d6; --hl:#1f5fae; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14181d; --fg:#e8ecf0; --muted:#9aa5b1; --grid:#2a313a; --bar:#4d6e99; --hl:#8fb8f0; }} }}
body {{ margin:0 auto; max-width:900px; padding:24px 16px; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,sans-serif; }}
h1 {{ font-size:22px; margin:0 0 4px }} h2 {{ font-size:16px; margin:32px 0 4px }}
.note,.meta {{ color:var(--muted); margin:0 0 8px; font-size:13px }}
svg {{ width:100%; height:auto; display:block }}
.grid {{ stroke:var(--grid) }} .tick,.value,.label {{ fill:var(--muted); font-size:11px }} .label {{ fill:var(--fg) }} .value {{ fill:var(--fg) }}
.bar {{ fill:var(--bar) }} .bar.hl {{ fill:var(--hl) }}
table {{ border-collapse:collapse; margin-top:8px }} td,th {{ padding:2px 12px 2px 0; text-align:left; font-size:13px }}
summary {{ cursor:pointer; color:var(--muted); font-size:13px }}
</style></head><body>
<h1>iRail CDN spike: benchmark results</h1>
<p class=meta>{meta}. Except for the three Home Assistant Yellow charts at the top, a single local x86_64 machine, not Raspberry Pi-class hardware. Time charts use log axes (each gridline is ten times the previous one); memory charts start at zero.</p>
{''.join(sections)}
</body></html>"""


if __name__ == "__main__":
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "results"
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else results_dir / "2026-11-11-report.html"
    target.write_text(build(results_dir))
    print(f"wrote {target}")
