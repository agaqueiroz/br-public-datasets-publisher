from __future__ import annotations

import pandas as pd
import pyarrow.parquet as pq
import pytest

from br_publisher.infra.parquet import (
    ConversionResult,
    StreamingParquetConverter,
    to_publishable,
    write_row_groups,
)

from ..conftest import make_resource
from ..fakes import FakeReader


def _frames(count: int = 3) -> list[pd.DataFrame]:
    return [
        pd.DataFrame(
            {
                "periodo_referencia": [pd.Period("2024-06", freq="M")] * 2,
                "cid": [f"0{index}1", f"0{index}2"],
            }
        )
        for index in range(count)
    ]


def test_to_publishable_writes_the_period_as_text():
    # Parquet stores a pandas Period as a raw month ordinal (2024-06 -> 653),
    # which the Hub viewer, DuckDB and polars all read as a meaningless integer.
    frame = pd.DataFrame({"periodo_referencia": [pd.Period("2024-06", freq="M")], "cid": ["01234"]})
    result = to_publishable(frame)
    assert result["periodo_referencia"].tolist() == ["2024-06"]
    assert result["cid"].tolist() == ["01234"]


def test_to_publishable_does_not_mutate_the_caller_frame():
    frame = pd.DataFrame({"periodo_referencia": [pd.Period("2024-06", freq="M")]})
    to_publishable(frame)
    assert str(frame["periodo_referencia"].dtype) == "period[M]"


def test_to_publishable_copy_is_shallow(monkeypatch):
    # A deep copy would duplicate every column of a frame that already runs to
    # gigabytes, doubling peak memory to rewrite a single column.
    seen = {}
    original = pd.DataFrame.copy

    def spy(self, deep=True):
        seen["deep"] = deep
        return original(self, deep=deep)

    monkeypatch.setattr(pd.DataFrame, "copy", spy)
    to_publishable(pd.DataFrame({"periodo_referencia": [pd.Period("2024-06", freq="M")]}))
    assert seen["deep"] is False


def test_to_publishable_leaves_a_frame_without_the_column_alone():
    frame = pd.DataFrame({"cid": ["01234"]})
    assert to_publishable(frame) is frame


def test_write_row_groups_writes_one_row_group_per_chunk(tmp_path):
    destination = tmp_path / "2024-06.parquet"
    result = write_row_groups(iter(_frames(3)), destination)
    assert result == ConversionResult(rows=6, columns=2)
    assert pq.ParquetFile(destination).num_row_groups == 3


def test_write_row_groups_writes_the_period_as_text_on_every_chunk(tmp_path):
    destination = tmp_path / "2024-06.parquet"
    write_row_groups(iter(_frames(3)), destination)
    table = pq.read_table(destination)
    assert set(table.column("periodo_referencia").to_pylist()) == {"2024-06"}


def test_write_row_groups_never_leaves_a_partial_file_under_the_final_name(tmp_path):
    destination = tmp_path / "2024-06.parquet"

    def chunks():
        yield _frames(1)[0]
        raise RuntimeError("disco cheio")

    with pytest.raises(RuntimeError, match="disco cheio"):
        write_row_groups(chunks(), destination)
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part").exists()


def test_write_row_groups_rejects_a_chunk_whose_schema_drifts(tmp_path):
    destination = tmp_path / "2024-06.parquet"
    drifted = pd.DataFrame({"outra_coluna": ["x"]})

    # pyarrow raises while reconciling the drifted chunk against the pinned
    # schema -- the point is that it raises instead of writing an unreadable file.
    with pytest.raises(KeyError):
        write_row_groups(iter([_frames(1)[0], drifted]), destination)
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part").exists()


def test_write_row_groups_rejects_an_empty_stream(tmp_path):
    destination = tmp_path / "2024-06.parquet"
    with pytest.raises(ValueError, match="nenhum dado lido"):
        write_row_groups(iter([]), destination)


def test_converter_retries_the_next_encoding_when_one_fails_past_the_sample(tmp_path):
    # The encoding sniffed from the leading sample can be disproved a gigabyte
    # in, after rows are already written -- so the conversion restarts here.
    source = tmp_path / "res.csv"
    source.write_bytes("a;b\r\n1;2\r\n".encode("latin-1"))
    attempts: list[str | None] = []

    class Flaky(FakeReader):
        def open_chunks(self, path, resource, *, encoding=None):
            attempts.append(encoding)
            if encoding == "utf-8-sig":
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "invalido")
            return super().open_chunks(path, resource, encoding=encoding)

    converter = StreamingParquetConverter(reader=Flaky())
    result = converter.convert(make_resource(), source, tmp_path / "out.parquet")
    assert attempts == ["utf-8-sig", "cp1252"]
    assert result.rows == 1


def test_converter_raises_when_the_last_encoding_also_fails(tmp_path):
    source = tmp_path / "res.csv"
    source.write_bytes(b"a;b\r\n1;2\r\n")

    class AlwaysFails(FakeReader):
        def open_chunks(self, path, resource, *, encoding=None):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "invalido")

    converter = StreamingParquetConverter(reader=AlwaysFails(encodings=["utf-8-sig"]))
    with pytest.raises(UnicodeDecodeError):
        converter.convert(make_resource(), source, tmp_path / "out.parquet")


def test_converter_handles_a_spreadsheet_with_no_encoding_candidates(tmp_path):
    # resource_encodings returns [] for a spreadsheet; the converter must still
    # make exactly one attempt, with encoding=None.
    source = tmp_path / "res.csv"
    source.write_bytes("a;b\r\n1;2\r\n".encode("latin-1"))
    reader = FakeReader(encodings=[])
    StreamingParquetConverter(reader=reader).convert(make_resource(), source, tmp_path / "out.parquet")
    assert reader.opened == [(source, None)]
