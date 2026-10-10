# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Apache Parquet columnar export for financial statements."""

from __future__ import annotations

import importlib
import io
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from ..input_validator import InputValidator
from ..privacy import redact_record

__all__ = [
    "ParquetStreamWriter",
    "export_parquet",
    "export_parquet_stream",
]


class ParquetStreamWriter:
    """Stream records in chunked batches directly to an Apache Parquet destination."""

    def __init__(
        self,
        output_path: str | Path,
        *,
        schema: Any,
        batch_size: int = 1000,
        compression: str = "snappy",
        redact_pii: bool = False,
    ) -> None:
        """Initialize the Parquet streaming writer with validated schema and destination."""
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size <= 0
        ):
            raise ValueError("batch_size must be a positive integer")
        try:
            self._pa = importlib.import_module("pyarrow")
            self._pq = importlib.import_module("pyarrow.parquet")
        except ImportError as exc:
            raise ImportError(
                "Install bankstatementparser[parquet] for streaming Parquet export"
            ) from exc

        names = set(schema.names)
        if len(names) != len(schema.names):
            raise ValueError("Parquet schema field names must be unique")
        self._schema = schema
        self._names = names
        self._required = [field.name for field in schema if not field.nullable]
        self._batch_size = batch_size
        self._compression = compression
        self._redact_pii = redact_pii

        self._destination = InputValidator().validate_output_file_path(
            str(output_path)
        )
        with tempfile.NamedTemporaryFile(
            dir=self._destination.parent,
            prefix=".bsp_",
            suffix=".parquet.tmp",
            delete=False,
        ) as temporary:
            self._temp_path = Path(temporary.name)

        self._writer = self._pq.ParquetWriter(
            self._temp_path, self._schema, compression=self._compression
        )
        self._writer.__enter__()
        self._batch: list[dict[str, Any]] = []
        self._rows_written = 0
        self._closed = False

    @property
    def rows_written(self) -> int:
        """Return the total number of records successfully written."""
        return self._rows_written

    def write_record(self, record: Mapping[str, Any]) -> None:
        """Validate, redact, buffer and write a single statement record."""
        if self._closed:
            raise ValueError("Cannot write to a closed ParquetStreamWriter")
        row = redact_record(record) if self._redact_pii else dict(record)
        if set(row) - self._names:
            raise ValueError(
                "Record contains fields absent from the Parquet schema"
            )
        if any(row.get(name) is None for name in self._required):
            raise ValueError("Record is missing a required Parquet field")
        self._batch.append(row)
        self._rows_written += 1
        if len(self._batch) >= self._batch_size:
            self.flush()

    def write_batch(self, records: Iterable[Mapping[str, Any]]) -> None:
        """Write an iterable sequence of records to the stream."""
        for record in records:
            self.write_record(record)

    def flush(self) -> None:
        """Flush the current buffered batch of records to disk."""
        if self._batch:
            self._writer.write_table(
                self._pa.Table.from_pylist(self._batch, schema=self._schema)
            )
            self._batch = []

    def close(self) -> int:
        """Flush pending batches, finalize file and atomically commit to destination."""
        if self._closed:
            return self._rows_written
        try:
            self.flush()
            self._writer.__exit__(None, None, None)
            os.replace(self._temp_path, self._destination)
            self._closed = True
        finally:
            self._temp_path.unlink(missing_ok=True)
        return self._rows_written

    def __enter__(self) -> ParquetStreamWriter:
        """Enter context manager scope."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit context manager, committing on success or removing temp file on error."""
        try:
            if exc_type is None:
                self.close()
            else:
                self._writer.__exit__(exc_type, exc_val, exc_tb)
        finally:
            self._temp_path.unlink(missing_ok=True)


def _convert_records(transactions: Iterable[Any]) -> list[dict[str, Any]]:
    """Convert an iterable of objects or dicts into a list of row dicts."""
    records: list[dict[str, Any]] = []
    for item in transactions:
        if isinstance(item, dict):
            records.append(item)
        elif hasattr(item, "model_dump"):
            records.append(item.model_dump())
        elif hasattr(item, "to_dict"):
            records.append(item.to_dict())
        elif hasattr(item, "__dict__"):
            records.append(
                {
                    k: v
                    for k, v in item.__dict__.items()
                    if not k.startswith("_")
                }
            )
        else:
            records.append({"value": str(item)})
    return records


def export_parquet(
    transactions: Iterable[Any] | pd.DataFrame,
    output_path: str | Path | None = None,
    compression: str = "snappy",
    *,
    redact_pii: bool = False,
) -> bytes:
    """Export statement transactions to Apache Parquet format.

    Args:
        transactions: Sequence of transactions, dictionaries, or a pandas DataFrame.
        output_path: Optional file path to write the Parquet file to.
        compression: Compression codec ('snappy', 'gzip', 'zstd', None).
        redact_pii: Mask identities, narratives and provenance fields.

    Returns:
        Parquet file contents as bytes.
    """
    validated_destination = (
        InputValidator().validate_output_file_path(str(output_path))
        if output_path is not None
        else None
    )
    if isinstance(transactions, pd.DataFrame):
        df = transactions.copy()
    else:
        records = _convert_records(transactions)
        df = pd.DataFrame(records)

    if redact_pii:
        df = pd.DataFrame(
            [redact_record(row) for row in df.to_dict("records")],
            columns=df.columns,
        )

    buf = io.BytesIO()
    try:
        df.to_parquet(buf, compression=compression, engine="pyarrow")
    except ImportError as exc:
        raise ImportError(
            "Apache Parquet export requires 'pyarrow' or 'fastparquet'. "
            "Install with: pip install 'bankstatementparser[parquet]' or pip install pyarrow"
        ) from exc
    parquet_bytes = buf.getvalue()

    if validated_destination is not None:
        validated_destination.write_bytes(parquet_bytes)

    return parquet_bytes


def export_parquet_stream(
    records: Iterable[Mapping[str, Any]],
    output_path: str | Path,
    *,
    schema: Any,
    batch_size: int = 10000,
    compression: str = "snappy",
    redact_pii: bool = False,
) -> int:
    """Write bounded Parquet batches atomically using an explicit Arrow schema.

    Supply a ``pyarrow.Schema`` covering all input keys, with adequate Decimal
    precision/scale and string types for fields being redacted. Missing nullable
    fields become null. Unknown fields, missing required fields and values that
    cannot be represented fail without replacing an existing destination.
    Returns the written row count; unlike export_parquet, no file bytes are
    retained. Memory depends on batch size and individual record sizes.
    """
    with ParquetStreamWriter(
        output_path,
        schema=schema,
        batch_size=batch_size,
        compression=compression,
        redact_pii=redact_pii,
    ) as writer:
        writer.write_batch(records)
        return writer.rows_written
