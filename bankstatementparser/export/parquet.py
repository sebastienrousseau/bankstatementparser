# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Apache Parquet columnar export for financial statements."""

from __future__ import annotations

import io
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd


def export_parquet(
    transactions: Iterable[Any] | pd.DataFrame,
    output_path: str | Path | None = None,
    compression: str = "snappy",
) -> bytes:
    """Export statement transactions to Apache Parquet format.

    Args:
        transactions: Sequence of transactions, dictionaries, or a pandas DataFrame.
        output_path: Optional file path to write the Parquet file to.
        compression: Compression codec ('snappy', 'gzip', 'zstd', None).

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
