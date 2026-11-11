"""Decode every file with one reader and print a single JSON line: time, peak memory, size, a digest of the values.

Run one reader per process, so peak memory figures stay separate (compare_all.py does this for all of them):
  uv run --group experiments python experiments/cdn/bench_readers.py stdlib|pyarrow|arro3|nanoarrow [DIR]
Each reader decodes every column of the 4 tables and all connection pages into Python lists. The digest lets
compare_all.py check that all readers return identical values.
"""

import hashlib
import json
import statistics
import sys
import time

from _common import data_dir, files, installed_mb, rss_mb

REPEAT = 3
DISTRIBUTIONS = {"stdlib": [], "pyarrow": ["pyarrow"], "arro3": ["arro3-core", "arro3-io"], "nanoarrow": ["nanoarrow"]}


def make_reader(name):
    if name == "stdlib":
        from pyrail.cdn.arrow import read_table

        return lambda path: read_table(path.read_bytes())
    if name == "pyarrow":
        import pyarrow.ipc as pa_ipc

        return lambda path: pa_ipc.open_file(path).read_all().to_pydict()
    if name == "arro3":
        from arro3.io import read_ipc

        def read(path):
            table = read_ipc(str(path))
            table = table.read_all() if hasattr(table, "read_all") else table
            return {column: table.column(column).to_pylist() for column in table.column_names}

        return read
    if name == "nanoarrow":
        import io

        import nanoarrow as na
        from nanoarrow import ipc

        def read(path):
            # The files have no leading Schema message, so nanoarrow's stream reader rejects them (the 8 bytes
            # skipped are the "ARROW1" magic and its padding).
            stream = na.ArrayStream(ipc.InputStream.from_readable(io.BytesIO(path.read_bytes()[8:])))
            names = [field.name for field in stream.schema.fields]
            columns = {name: [] for name in names}
            for batch in stream:
                for index, name in enumerate(names):
                    columns[name].extend(batch.child(index).to_pylist())
            return columns

        return read
    raise SystemExit("reader must be one of: " + ", ".join(DISTRIBUTIONS))


def main() -> None:
    name = sys.argv.pop(1)
    paths = files(data_dir())
    result = {"reader": name, "installed_mb": round(installed_mb(*DISTRIBUTIONS[name]), 1), "files": len(paths)}
    read = make_reader(name)
    base = rss_mb()
    timings = []
    try:
        tables = []
        for _ in range(REPEAT):
            tables = []  # drop the previous pass first, so the peak memory is that of one pass
            start = time.perf_counter()
            tables = [read(path) for path in paths]
            timings.append((time.perf_counter() - start) * 1000)
    except Exception as error:  # noqa: BLE001
        result["error"] = f"{type(error).__name__}: {error}"
    else:
        digest = hashlib.sha256()
        for table in tables:
            digest.update(repr(table).encode())
        result.update(
            rows=sum(len(next(iter(table.values()))) for table in tables),
            ms_best=round(min(timings)),
            ms_median=round(statistics.median(timings)),
            rss_start_mb=base,
            rss_peak_mb=rss_mb(),
            digest=digest.hexdigest()[:16],
        )
    print(json.dumps(result))


main()
