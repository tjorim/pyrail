"""Show that the CDN files have no Schema message in front of the record batches (needs pyarrow).

Run: uv run --with pyarrow python check_schema_message.py [DIR]
"""

import pyarrow as pa
import pyarrow.ipc as ipc

from _common import data_dir, files

for path in files(data_dir()):
    raw = path.read_bytes()
    first = ipc.read_message(pa.BufferReader(raw[8:])).type  # skip the 8 byte "ARROW1" magic plus padding
    print(f"{path.name:16} first message: {first}")
