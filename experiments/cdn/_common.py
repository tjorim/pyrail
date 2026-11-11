"""Shared helpers for the experiment scripts."""

from importlib import metadata
from pathlib import Path
import resource
import sys

TABLES = ("stops", "routes", "trips", "transfers")


def data_dir(args: list[str] | None = None) -> Path:
    """Return the data directory given as the first argument (default: ./data)."""
    args = sys.argv[1:] if args is None else args
    path = Path(args[0] if args else "data")
    if not (path / "stops.arrow").exists():
        msg = f"no data in {path}: run fetch_data.py first"
        raise SystemExit(msg)
    return path


def files(path: Path) -> list[Path]:
    """The four tables and every connection page in the data directory."""
    return [path / f"{name}.arrow" for name in TABLES] + sorted((path / "pages").glob("p*.arrow"))


def rss_mb() -> int:
    """Peak resident set size of this process in MB (Linux reports KB)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


def version(distribution: str) -> str:
    """Installed version of a distribution, or 'not installed'."""
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "not installed"


def installed_mb(*distributions: str) -> float:
    """Total size on disk of the files of the given distributions, in MB."""
    total = 0
    for name in distributions:
        for item in metadata.distribution(name).files or []:
            located = Path(str(item.locate()))
            if located.is_file():
                total += located.stat().st_size
    return total / 2**20
