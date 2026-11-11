"""Minimal reader for the Apache Arrow IPC *files* that the iRail CDN publishes.

The CDN files (stops, routes, trips, transfers and connection pages) have no Schema message in front of the
record batches: the schema is only in the footer. Stream readers such as nanoarrow reject such files, so this
module reads the footer for the schema and the block offsets and decodes each record batch from its buffers.
It needs nothing beyond the standard library, which keeps pyarrow (about 166 MB installed) out of pyrail's
dependencies.

Only what the CDN files use is supported: 8 to 64 bit integers, 32 and 64 bit floats, UTF-8 strings and
booleans, in uncompressed record batches. Anything else raises :class:`ArrowError`.
"""

from collections.abc import Callable
from dataclasses import dataclass
import struct
from typing import Any

from pyrail.exceptions import PyRailError

__all__ = ["ArrowError", "read_table"]

_MAGIC = b"ARROW1"
_TAIL_SIZE = len(_MAGIC) + 4  # footer length (int32) + closing magic
_BLOCK_SIZE = 24  # Block struct: offset int64, metaDataLength int32 + 4 padding bytes, bodyLength int64

# Message.header_type and Type enum values from the Arrow Flatbuffers schema (Message.fbs / Schema.fbs).
_HEADER_RECORD_BATCH = 3
_TYPE_INT = 2
_TYPE_FLOATING_POINT = 3
_TYPE_UTF8 = 5
_TYPE_BOOL = 6
_PRECISION_SINGLE = 1
_PRECISION_DOUBLE = 2

_INT_FORMATS = {
    (8, True): "b",
    (8, False): "B",
    (16, True): "h",
    (16, False): "H",
    (32, True): "i",
    (32, False): "I",
    (64, True): "q",
    (64, False): "Q",
}
_FLOAT_FORMATS = {_PRECISION_SINGLE: "f", _PRECISION_DOUBLE: "d"}
_UTF8 = "utf8"
_BOOL = "bool"


def _unpack(fmt: str, buf: memoryview, pos: int) -> int:
    """Read one little-endian integer; the struct module is untyped, so narrow its result here."""
    return int(struct.unpack_from(fmt, buf, pos)[0])


class ArrowError(PyRailError):
    """Raised when an Arrow IPC file is malformed or uses a feature this reader does not support."""


class _Table:
    """Read-only view of a FlatBuffers table, with just the accessors the Arrow metadata needs."""

    def __init__(self, buf: memoryview, pos: int) -> None:
        self._buf = buf
        self._pos = pos
        self._vtable = pos - _unpack("<i", buf, pos)
        self._vtable_size = _unpack("<H", buf, self._vtable)

    def _field_offset(self, index: int) -> int:
        """Return the offset of a field inside the table, or 0 when the field is absent."""
        entry = 4 + 2 * index
        if entry >= self._vtable_size:
            return 0
        return _unpack("<H", self._buf, self._vtable + entry)

    def _indirect(self, index: int) -> int | None:
        """Follow an offset field to the position it points at, or None when the field is absent."""
        offset = self._field_offset(index)
        if not offset:
            return None
        pos = self._pos + offset
        return pos + _unpack("<I", self._buf, pos)

    def scalar(self, index: int, fmt: str) -> int:
        """Read a scalar field; an absent field is 0 (the Arrow schema's default for every scalar used here)."""
        offset = self._field_offset(index)
        return _unpack(fmt, self._buf, self._pos + offset) if offset else 0

    def table(self, index: int) -> "_Table | None":
        """Read a nested table, or None when absent."""
        pos = self._indirect(index)
        return None if pos is None else _Table(self._buf, pos)

    def string(self, index: int) -> str | None:
        """Read a string field, or None when absent."""
        pos = self._indirect(index)
        if pos is None:
            return None
        length = _unpack("<I", self._buf, pos)
        return bytes(self._buf[pos + 4 : pos + 4 + length]).decode()

    def vector(self, index: int) -> tuple[int, int]:
        """Return the (start, length) of a vector's elements; an absent vector is (0, 0)."""
        pos = self._indirect(index)
        if pos is None:
            return 0, 0
        return pos + 4, _unpack("<I", self._buf, pos)

    def tables(self, index: int) -> list["_Table"]:
        """Read a vector of tables."""
        start, length = self.vector(index)
        result = []
        for item in range(length):
            pos = start + 4 * item
            result.append(_Table(self._buf, pos + _unpack("<I", self._buf, pos)))
        return result


@dataclass(frozen=True, slots=True)
class _Column:
    name: str
    kind: str  # a struct format character for numbers, or _UTF8 / _BOOL


def _root(buf: memoryview, pos: int) -> _Table:
    return _Table(buf, pos + _unpack("<I", buf, pos))


def _column(field: _Table) -> _Column:
    name = field.string(0) or ""
    type_type = field.scalar(2, "<B")
    type_table = field.table(3)
    if field.table(4) is not None:
        msg = f"column {name!r} is dictionary-encoded, which is not supported"
        raise ArrowError(msg)
    if type_table is not None and type_type == _TYPE_INT:
        key = (type_table.scalar(0, "<i"), bool(type_table.scalar(1, "<B")))
        if key in _INT_FORMATS:
            return _Column(name, _INT_FORMATS[key])
    elif type_table is not None and type_type == _TYPE_FLOATING_POINT:
        precision = type_table.scalar(0, "<h")
        if precision in _FLOAT_FORMATS:
            return _Column(name, _FLOAT_FORMATS[precision])
    elif type_type == _TYPE_UTF8:
        return _Column(name, _UTF8)
    elif type_type == _TYPE_BOOL:
        return _Column(name, _BOOL)
    msg = f"column {name!r} has an unsupported Arrow type (type id {type_type})"
    raise ArrowError(msg)


def _bits(buf: memoryview, start: int, length: int, rows: int) -> list[bool]:
    """Unpack a bitmap (validity or boolean data) into one bool per row."""
    if length * 8 < rows:
        msg = "bitmap is shorter than the row count"
        raise ArrowError(msg)
    raw = bytes(buf[start : start + length])
    return [bool(raw[i >> 3] >> (i & 7) & 1) for i in range(rows)]


def _decode_column(
    buf: memoryview,
    kind: str,
    rows: int,
    null_count: int,
    buffer_at: Callable[[int], tuple[int, int]],
) -> tuple[list[Any], int]:
    """Decode one column; return its values and the number of buffers it used."""
    valid = _bits(buf, *buffer_at(0), rows) if null_count else None
    values: list[Any]
    if kind == _UTF8:
        offsets_start, offsets_length = buffer_at(1)
        data_start, data_length = buffer_at(2)
        if offsets_length < 4 * (rows + 1):
            msg = "string offsets are shorter than the row count"
            raise ArrowError(msg)
        offsets = struct.unpack_from(f"<{rows + 1}i", buf, offsets_start)
        if rows and (offsets[rows] > data_length or offsets[0] < 0):
            msg = "string offsets point outside the data buffer"
            raise ArrowError(msg)
        data = bytes(buf[data_start : data_start + data_length])
        values = [data[offsets[i] : offsets[i + 1]].decode() for i in range(rows)]
        used = 3
    elif kind == _BOOL:
        values = _bits(buf, *buffer_at(1), rows)
        used = 2
    else:
        start, length = buffer_at(1)
        size = struct.calcsize(kind)
        if length < size * rows:
            msg = "data buffer is shorter than the row count"
            raise ArrowError(msg)
        values = list(struct.unpack_from(f"<{rows}{kind}", buf, start))
        used = 2
    if valid is not None:
        values = [value if is_valid else None for value, is_valid in zip(values, valid, strict=True)]
    return values, used


def _read_batch(buf: memoryview, columns: list[_Column], block: tuple[int, int]) -> dict[str, list[Any]]:
    offset, meta_length = block
    message = _root(buf, offset + 8)  # skip the 0xFFFFFFFF continuation marker and the metadata length
    if message.scalar(1, "<B") != _HEADER_RECORD_BATCH:
        msg = "block does not hold a record batch"
        raise ArrowError(msg)
    batch = message.table(2)
    if batch is None:
        msg = "record batch message has no header"
        raise ArrowError(msg)
    if batch.table(3) is not None:
        msg = "compressed record batches are not supported"
        raise ArrowError(msg)
    rows = batch.scalar(0, "<q")
    nodes_start, nodes_count = batch.vector(1)
    buffers_start, buffers_count = batch.vector(2)
    body = offset + meta_length
    if nodes_count != len(columns):
        msg = "record batch does not match the schema"
        raise ArrowError(msg)

    first_buffer = 0
    result: dict[str, list[Any]] = {}
    for index, column in enumerate(columns):

        def buffer_at(k: int, first: int = first_buffer) -> tuple[int, int]:
            if first + k >= buffers_count:
                msg = "record batch has too few buffers"
                raise ArrowError(msg)
            buffer_offset = _unpack("<q", buf, buffers_start + 16 * (first + k))
            length = _unpack("<q", buf, buffers_start + 16 * (first + k) + 8)
            start = body + buffer_offset
            if buffer_offset < 0 or length < 0 or start + length > len(buf):
                msg = "buffer lies outside the file"
                raise ArrowError(msg)
            return start, length

        null_count = _unpack("<q", buf, nodes_start + 16 * index + 8)
        values, used = _decode_column(buf, column.kind, rows, null_count, buffer_at)
        first_buffer += used
        result[column.name] = values
    return result


def read_table(data: bytes | bytearray | memoryview) -> dict[str, list[Any]]:
    """Read an Arrow IPC file into a dict that maps each column name to its list of values.

    Null values become None. Record batches are concatenated in file order.

    Raises:
        ArrowError: If the data is not a valid Arrow IPC file, or uses compression, dictionary encoding or a
            column type this reader does not support.

    """
    buf = memoryview(data)
    if len(buf) < 2 * len(_MAGIC) + 4 or bytes(buf[: len(_MAGIC)]) != _MAGIC or bytes(buf[-len(_MAGIC) :]) != _MAGIC:
        msg = "not an Arrow IPC file"
        raise ArrowError(msg)
    try:
        return _read_file(buf)
    except (struct.error, IndexError, ValueError, UnicodeDecodeError, OverflowError) as error:
        msg = f"malformed Arrow file: {error}"
        raise ArrowError(msg) from error


def _read_file(buf: memoryview) -> dict[str, list[Any]]:
    footer_length = _unpack("<i", buf, len(buf) - _TAIL_SIZE)
    if footer_length <= 0 or footer_length > len(buf) - _TAIL_SIZE:
        msg = "footer length is out of range"
        raise ArrowError(msg)
    footer = _root(buf, len(buf) - _TAIL_SIZE - footer_length)
    schema = footer.table(1)
    if schema is None:
        msg = "footer has no schema"
        raise ArrowError(msg)
    if schema.scalar(0, "<h") != 0:
        msg = "big-endian Arrow data is not supported"
        raise ArrowError(msg)
    columns = [_column(field) for field in schema.tables(1)]
    if footer.vector(2)[1]:
        msg = "dictionary batches are not supported"
        raise ArrowError(msg)

    table: dict[str, list[Any]] = {column.name: [] for column in columns}
    blocks_start, blocks_count = footer.vector(3)
    for index in range(blocks_count):
        block = blocks_start + _BLOCK_SIZE * index
        offset = _unpack("<q", buf, block)
        meta_length = _unpack("<i", buf, block + 8)
        if offset < 0 or meta_length <= 0 or offset + meta_length > len(buf):
            msg = "record batch block lies outside the file"
            raise ArrowError(msg)
        for name, values in _read_batch(buf, columns, (offset, meta_length)).items():
            table[name].extend(values)
    return table
