"""Try nanoarrow on the CDN files, and on the same table re-written as an IPC stream.

Run: uv run --group experiments python experiments/cdn/probe_nanoarrow.py [DIR]
Expected: the CDN file fails ("expected Schema"), the re-written stream works.
"""

import io

import nanoarrow as na
from nanoarrow import ipc
import pyarrow as pa
import pyarrow.ipc as pa_ipc

from _common import data_dir

raw = (data_dir() / "stops.arrow").read_bytes()
for label, data in (("CDN file, magic skipped", raw[8:]),):
    try:
        stream = na.ArrayStream(ipc.InputStream.from_readable(io.BytesIO(data)))
        print(label, "-> schema", [f.name for f in stream.schema.fields])
    except Exception as error:  # noqa: BLE001
        print(label, "-> FAILED:", error)

table = pa_ipc.open_file(raw).read_all()
sink = io.BytesIO()
with pa_ipc.new_stream(sink, table.schema) as writer:
    writer.write_table(table)
sink.seek(0)
stream = na.ArrayStream(ipc.InputStream.from_readable(sink))
print("same table as an IPC stream -> OK,", sum(len(batch) for batch in stream), "rows")
