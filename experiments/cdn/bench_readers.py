"""Time and measure memory for one reader over the tables and all connection pages.

Run (one reader per process, so the peak memory figures stay separate):
  uv run python experiments/cdn/bench_readers.py stdlib [DIR]
  uv run python experiments/cdn/bench_readers.py pyarrow [DIR]
  uv run --with arro3-io python experiments/cdn/bench_readers.py arro3 [DIR]
Each reader decodes every file into Python lists (all columns, including the iri strings).
"""

import sys
import time

from _common import data_dir, files, rss_mb

reader = sys.argv.pop(1)
paths = files(data_dir())
base = rss_mb()

if reader == "stdlib":
    from pyrail.cdn.arrow import read_table

    def read(path):
        return read_table(path.read_bytes())

elif reader == "pyarrow":
    import pyarrow.ipc as pa_ipc

    def read(path):
        return pa_ipc.open_file(path).read_all().to_pydict()

elif reader == "arro3":
    from arro3.io import read_ipc

    def read(path):
        table = read_ipc(str(path))
        table = table.read_all() if hasattr(table, "read_all") else table
        return {name: table.column(name).to_pylist() for name in table.column_names}

else:
    raise SystemExit("reader must be stdlib, pyarrow or arro3")

start = time.perf_counter()
tables = [read(path) for path in paths]
elapsed = (time.perf_counter() - start) * 1000
rows = sum(len(next(iter(table.values()))) for table in tables)
print(f"{reader}: {len(paths)} files, {rows} rows, {elapsed:.0f} ms, peak RSS {base} -> {rss_mb()} MB")
