"""Tests for the standard-library Arrow IPC file reader."""

from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.ipc as pa_ipc
import pytest

from pyrail.cdn.arrow import ArrowError, read_table
from pyrail.exceptions import PyRailError

DATA = Path(__file__).parent / "data"


def _write(table: pa.Table, *, batch_size: int | None = None, compression: str | None = None) -> bytes:
    sink = BytesIO()
    options = pa_ipc.IpcWriteOptions(compression=compression)
    with pa_ipc.new_file(sink, table.schema, options=options) as writer:
        for batch in table.to_batches(max_chunksize=batch_size):
            writer.write_batch(batch)
    return sink.getvalue()


def _table(**columns: tuple[pa.DataType, Sequence[Any]]) -> pa.Table:
    return pa.table({name: pa.array(values, type=kind) for name, (kind, values) in columns.items()})


class TestRealCdnFile:
    """A trimmed-down copy of the real stops.arrow from the iRail CDN (release nmbs-sncb-20261110-5d71e5b6)."""

    def test_has_no_leading_schema_message(self) -> None:
        """The CDN files start with a record batch, which is why stream readers reject them."""
        raw = DATA.joinpath("stops.arrow").read_bytes()
        assert pa_ipc.read_message(pa.BufferReader(raw[8:])).type == "record batch"

    def test_matches_pyarrow(self) -> None:
        """Check: matches pyarrow."""
        raw = DATA.joinpath("stops.arrow").read_bytes()
        assert read_table(raw) == pa_ipc.open_file(raw).read_all().to_pydict()

    def test_known_values(self) -> None:
        """Check: known values."""
        table = read_table(DATA.joinpath("stops.arrow").read_bytes())
        assert list(table) == ["name", "lat", "lon", "parentIdx", "minTransferTime", "iri", "regionIri"]
        assert {len(column) for column in table.values()} == {635}
        assert table["name"][0] == "FRANKFURT(MAIN) SUD"
        assert table["iri"][0] == "http://irail.be/stations/NMBS/008011065"
        assert table["lat"][0] == pytest.approx(50.0992)
        assert table["parentIdx"][0] == -1
        assert table["minTransferTime"][0] == 300
        assert set(table["regionIri"]) == {None}

    def test_accepts_bytearray_and_memoryview(self) -> None:
        """Check: accepts bytearray and memoryview."""
        raw = DATA.joinpath("stops.arrow").read_bytes()
        expected = read_table(raw)
        assert read_table(bytearray(raw)) == expected
        assert read_table(memoryview(raw)) == expected


class TestTypes:
    """Round trips of every supported column type against what pyarrow wrote."""

    @pytest.mark.parametrize(
        ("kind", "values"),
        [
            (pa.int8(), [-128, 0, 127]),
            (pa.uint8(), [0, 1, 255]),
            (pa.int16(), [-32768, 0, 32767]),
            (pa.uint16(), [0, 1, 65535]),
            (pa.int32(), [-(2**31), 0, 2**31 - 1]),
            (pa.uint32(), [0, 1, 2**32 - 1]),
            (pa.int64(), [-(2**63), 0, 2**63 - 1]),
            (pa.uint64(), [0, 1, 2**64 - 1]),
            (pa.float32(), [0.0, 1.5, -2.25]),
            (pa.float64(), [0.1, -1e300, 3.141592653589793]),
            (pa.bool_(), [True, False, True]),
            (pa.string(), ["", "Gent-Sint-Pieters", "Liège-Guillemins", "日本語"]),
        ],
    )
    def test_round_trip(self, kind: pa.DataType, values: list[Any]) -> None:
        """Check: round trip."""
        table = _table(column=(kind, values))
        assert read_table(_write(table)) == {"column": values}

    @pytest.mark.parametrize(
        ("kind", "values"),
        [
            (pa.int32(), [1, None, 3, None]),
            (pa.float64(), [None, 2.5, None]),
            (pa.bool_(), [True, None, False]),
            (pa.string(), ["a", None, "", None]),
            (pa.string(), [None, None]),
        ],
    )
    def test_nulls_become_none(self, kind: pa.DataType, values: list[Any]) -> None:
        """Check: nulls become none."""
        assert read_table(_write(_table(column=(kind, values)))) == {"column": values}

    def test_more_than_eight_rows_in_bitmaps(self) -> None:
        """Check: more than eight rows in bitmaps."""
        values = [index % 3 == 0 for index in range(100)]
        nullable = [None if index % 7 == 0 else value for index, value in enumerate(values)]
        table = _table(flag=(pa.bool_(), values), maybe=(pa.bool_(), nullable))
        assert read_table(_write(table)) == {"flag": values, "maybe": nullable}

    def test_several_columns_keep_their_buffers_apart(self) -> None:
        """Check: several columns keep their buffers apart."""
        table = _table(
            number=(pa.int32(), [1, 2, 3]),
            text=(pa.string(), ["x", None, "zzz"]),
            ratio=(pa.float64(), [0.5, 1.5, None]),
            flag=(pa.bool_(), [True, False, None]),
            small=(pa.uint8(), [7, 8, 9]),
        )
        assert read_table(_write(table)) == table.to_pydict()

    def test_multiple_record_batches_are_concatenated(self) -> None:
        """Check: multiple record batches are concatenated."""
        table = _table(number=(pa.int32(), list(range(25))), text=(pa.string(), [str(i) for i in range(25)]))
        raw = _write(table, batch_size=10)
        assert pa_ipc.open_file(raw).num_record_batches == 3
        assert read_table(raw) == table.to_pydict()

    def test_empty_table(self) -> None:
        """Check: empty table."""
        table = _table(number=(pa.int32(), []), text=(pa.string(), []))
        assert read_table(_write(table)) == {"number": [], "text": []}


class TestUnsupported:
    """Features outside what the CDN files use fail with ArrowError, never with a wrong result."""

    @pytest.mark.parametrize("compression", ["zstd", "lz4"])
    def test_compressed_batches(self, compression: str) -> None:
        """Check: compressed batches."""
        raw = _write(_table(number=(pa.int32(), list(range(1000)))), compression=compression)
        with pytest.raises(ArrowError, match="compressed"):
            read_table(raw)

    @pytest.mark.parametrize(
        "kind",
        [pa.date32(), pa.timestamp("ms"), pa.large_string(), pa.binary(), pa.list_(pa.int32()), pa.float16()],
    )
    def test_unsupported_column_types(self, kind: pa.DataType) -> None:
        """Check: unsupported column types."""
        raw = _write(pa.table({"column": pa.array([], type=kind)}))
        with pytest.raises(ArrowError, match="unsupported Arrow type"):
            read_table(raw)

    def test_dictionary_encoded_columns(self) -> None:
        """Check: dictionary encoded columns."""
        raw = _write(pa.table({"column": pa.array(["a", "b", "a"]).dictionary_encode()}))
        with pytest.raises(ArrowError, match="dictionary"):
            read_table(raw)


class TestMalformed:
    """Damaged input raises ArrowError, which is a PyRailError, and nothing else."""

    def test_is_a_pyrail_error(self) -> None:
        """Check: is a pyrail error."""
        assert issubclass(ArrowError, PyRailError)

    @pytest.mark.parametrize("data", [b"", b"ARROW1", b"not an arrow file at all", b"ARROW1" + b"\x00" * 40])
    def test_not_an_arrow_file(self, data: bytes) -> None:
        """Check: not an arrow file."""
        with pytest.raises(ArrowError):
            read_table(data)

    def test_truncated_files_never_escape_as_other_errors(self) -> None:
        """Check: truncated files never escape as other errors."""
        raw = DATA.joinpath("stops.arrow").read_bytes()
        for length in [*range(60), 1000, 20000, len(raw) - 100, len(raw) - 11, len(raw) - 1]:
            with pytest.raises(ArrowError):
                read_table(raw[:length])

    def test_damaged_files_never_escape_as_other_errors(self) -> None:
        """Check: damaged files never escape as other errors."""
        raw = bytearray(_write(_table(number=(pa.int32(), [1, 2, 3]), text=(pa.string(), ["a", "bb", None]))))
        for position in range(8, len(raw) - 6):
            damaged = bytearray(raw)
            damaged[position] ^= 0xFF
            try:
                read_table(damaged)
            except ArrowError:
                continue  # rejected: fine; a damaged value that still decodes is also fine

    def test_footer_length_out_of_range(self) -> None:
        """Check: footer length out of range."""
        raw = bytearray(DATA.joinpath("stops.arrow").read_bytes())
        raw[-10:-6] = (2**30).to_bytes(4, "little")
        with pytest.raises(ArrowError, match="footer length"):
            read_table(raw)

    def test_buffer_outside_the_file(self) -> None:
        """Check: buffer outside the file."""
        raw = _write(_table(number=(pa.int32(), list(range(100)))))
        footer_start = len(raw) - 10 - int.from_bytes(raw[-10:-6], "little")
        # Cut the body short but keep the footer, so the block points past the data.
        broken = raw[:200] + raw[footer_start:]
        with pytest.raises(ArrowError):
            read_table(broken)
