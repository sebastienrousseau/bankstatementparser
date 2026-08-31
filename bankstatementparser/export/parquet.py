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

    # Normalize column types for Parquet compatibility
    for col in df.columns:
        # Convert Decimals and complex objects to string if pyarrow fails on object dtype
        if df[col].dtype == "object":
            df[col] = df[col].apply(
                lambda x: (
                    str(x)
                    if x is not None and not isinstance(x, (str, bytes))
                    else x
                )
            )

    buf = io.BytesIO()
    df.to_parquet(buf, compression=compression, engine="auto")
    parquet_bytes = buf.getvalue()

    if output_path is not None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(parquet_bytes)

    return parquet_bytes
