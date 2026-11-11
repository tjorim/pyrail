"""Shared helpers for the experiment scripts."""

from pathlib import Path
import resource
import sys

TABLES = ("stops", "routes", "trips", "transfers")


def data_dir() -> Path:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    if not (path / "stops.arrow").exists():
        msg = f"no data in {path}: run fetch_data.py first"
        raise SystemExit(msg)
    return path


def files(path: Path) -> list[Path]:
    return [path / f"{name}.arrow" for name in TABLES] + sorted((path / "pages").glob("p*.arrow"))


def rss_mb() -> int:
    """Peak resident set size of this process in MB (Linux reports KB)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
