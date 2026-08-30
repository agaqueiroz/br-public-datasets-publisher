"""Streaming conversion: one source file in, one Parquet out, one row group per chunk."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from br_publisher.domain.recipe import COMPRESSION, PERIOD_COLUMN
from br_publisher.library.models import SourceResource
from br_publisher.ports import SourceReader

LOGGER = logging.getLogger("brinss.publish")


@dataclass(frozen=True, slots=True)
class ConversionResult:
    rows: int
    columns: int


def to_publishable(frame: pd.DataFrame) -> pd.DataFrame:
    """Make a frame safe to read outside pandas.

    ``periodo_referencia`` arrives as a ``pandas.Period``, which Parquet stores
    as a pandas-specific extension type over a raw month ordinal (2024-06 is
    written as 653). Pandas round-trips it, but the viewer of the Hub, DuckDB
    and polars all see a meaningless integer -- so it goes out as "YYYY-MM" text.

    The copy is deliberately shallow: a deep one would duplicate every column of
    a frame that already runs to gigabytes on the heavy families, doubling peak
    memory to rewrite a single column. Under copy-on-write in pandas the
    caller's frame is still left untouched.
    """
    if PERIOD_COLUMN in frame.columns:
        frame = frame.copy(deep=False)
        frame[PERIOD_COLUMN] = frame[PERIOD_COLUMN].astype(str)
    return frame


def write_row_groups(
    chunks: Iterator[pd.DataFrame], destination: Path, *, compression: str = COMPRESSION
) -> ConversionResult:
    """Write chunks to Parquet via a .part file, so the final name is never truncated.

    A crash mid-write would otherwise leave a partial file under the name the
    cache trusts, and the next run would hand it to the Hub as a finished month.
    That mattered when the whole month was written in one call; it matters more
    now that the write spans hundreds of row groups and minutes.

    Chunks are written as they arrive and dropped, which is the whole point: the
    largest month is 25 GiB of CSV and 86 million rows, and holding it as one
    frame is what used to raise ``MemoryError``. Each chunk becomes one row
    group, which also serves whoever reads the result off the Hub.

    The schema of the first chunk is pinned for the rest. Every column is read
    as text, so the schema does not drift between chunks -- and if it ever does,
    ``write_table`` raises rather than quietly writing an unreadable file.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    writer = None
    rows = 0
    columns = 0

    try:
        for chunk in chunks:
            table = pa.Table.from_pandas(
                to_publishable(chunk), schema=writer.schema if writer else None, preserve_index=False
            )
            if writer is None:
                writer = pq.ParquetWriter(partial, table.schema, compression=compression)
                columns = table.num_columns
            writer.write_table(table)
            rows += table.num_rows
        if writer is None:
            # No chunks at all: pandas always yields at least one, even empty,
            # so this means the reader gave up before the header.
            raise ValueError(f"nenhum dado lido para {destination.name}")
        writer.close()
        writer = None
    except BaseException:
        if writer is not None:
            # Closing writes the footer, so it can fail too -- on a full disk it
            # is the likeliest thing to. Letting that escape would replace the
            # real cause and, worse, skip the unlink below, leaving behind the
            # very .part this function exists to prevent.
            with contextlib.suppress(Exception):
                writer.close()
        partial.unlink(missing_ok=True)
        raise

    partial.replace(destination)
    return ConversionResult(rows=rows, columns=columns)


@dataclass(frozen=True, slots=True)
class StreamingParquetConverter:
    """Stream one source into one Parquet, retrying only if the encoding was wrong.

    The loop exists for the encoding. The one sniffed from the leading sample
    can be disproved much later in the file -- a CSV that opens with a megabyte
    of plain ASCII and turns out to be cp1252 further down reads as UTF-8 right
    up to its first accented byte. By then rows have already been written, so
    unlike a whole-file read this cannot retry from the inside; the conversion
    is restarted here with the next candidate instead. ``write_row_groups``
    already deletes its ``.part`` on the way out, so each attempt starts clean.

    In practice this runs once: the published CSVs carry an accent in the header
    row, which settles the encoding in the first few bytes.
    """

    reader: SourceReader
    compression: str = COMPRESSION

    def convert(self, resource: SourceResource, source: Path, destination: Path) -> ConversionResult:
        encodings: list[str | None] = list(self.reader.encodings(source)) or [None]

        for position, encoding in enumerate(encodings):
            try:
                with self.reader.open_chunks(source, resource, encoding=encoding) as chunks:
                    return write_row_groups(chunks, destination, compression=self.compression)
            except UnicodeDecodeError:
                if position == len(encodings) - 1:
                    raise
                LOGGER.warning(
                    "  encoding '%s' falhou alem da amostra em '%s'; refazendo com '%s'",
                    encoding,
                    source.name,
                    encodings[position + 1],
                )

        raise AssertionError("unreachable: the last candidate either returns or raises")  # pragma: no cover
