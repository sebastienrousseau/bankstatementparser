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

from ..privacy import redact_record


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
    if isinstance(transactions, pd.DataFrame):
        df = transactions.copy()
    else:
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
        df = pd.DataFrame(records)

    if redact_pii:
        df = pd.DataFrame(
            [redact_record(row) for row in df.to_dict("records")],
            columns=df.columns,
        )

    # Preserve Decimal, date, and timestamp values: Arrow infers their native
    # logical types. Unsupported heterogeneous columns fail instead of silently
    # converting financial values to strings.
    buf = io.BytesIO()
    try:
        df.to_parquet(buf, compression=compression, engine="pyarrow")
    except ImportError as exc:
        raise ImportError(
            "Apache Parquet export requires 'pyarrow' or 'fastparquet'. "
            "Install with: pip install 'bankstatementparser[parquet]' or pip install pyarrow"
        ) from exc
    parquet_bytes = buf.getvalue()

    if output_path is not None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(parquet_bytes)

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
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size <= 0
    ):
        raise ValueError("batch_size must be a positive integer")
    try:
        pa = importlib.import_module("pyarrow")
        pq = importlib.import_module("pyarrow.parquet")
    except ImportError as exc:
        raise ImportError(
            "Install bankstatementparser[parquet] for streaming Parquet export"
        ) from exc
    names = set(schema.names)
    if len(names) != len(schema.names):
        raise ValueError("Parquet schema field names must be unique")
    required = [field.name for field in schema if not field.nullable]
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=".bsp_",
        suffix=".parquet.tmp",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    count = 0
    batch = []
    try:
        with pq.ParquetWriter(
            temporary_path, schema, compression=compression
        ) as writer:
            for record in records:
                row = redact_record(record) if redact_pii else dict(record)
                if set(row) - names:
                    raise ValueError(
                        "Record contains fields absent from the Parquet schema"
                    )
                if any(row.get(name) is None for name in required):
                    raise ValueError(
                        "Record is missing a required Parquet field"
                    )
                batch.append(row)
                count += 1
                if len(batch) == batch_size:
                    writer.write_table(
                        pa.Table.from_pylist(batch, schema=schema)
                    )
                    batch = []
            if batch:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return count
