"""Check that pyrail.cdn.arrow.read_table returns the same values as pyarrow (and arro3-io, if installed).

Run from the repository root:
  uv run python experiments/cdn/compare_readers.py [DIR]            # pyarrow is in the test group
  uv run --with arro3-io python experiments/cdn/compare_readers.py [DIR]
"""

from pyrail.cdn.arrow import read_table
import pyarrow.ipc as pa_ipc

from _common import data_dir, files

try:
    from arro3.io import read_ipc
except ImportError:
    read_ipc = None

mismatches = 0
for path in files(data_dir()):
    raw = path.read_bytes()
    mine = read_table(raw)
    results = {"pyarrow": pa_ipc.open_file(raw).read_all().to_pydict()}
    if read_ipc is not None:
        table = read_ipc(str(path))
        table = table.read_all() if hasattr(table, "read_all") else table
        results["arro3"] = {name: table.column(name).to_pylist() for name in table.column_names}
    for name, other in results.items():
        same = mine == other
        mismatches += not same
        print(f"{'OK  ' if same else 'DIFF'} {path.name:12} vs {name}")
print("mismatches:", mismatches)
