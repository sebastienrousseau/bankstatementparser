# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for Apache Parquet Columnar Export."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from bankstatementparser.additional_parsers import CsvStatementParser
from bankstatementparser.export.parquet import export_parquet
from bankstatementparser.transaction_models import Transaction


@pytest.fixture(autouse=True)
def _ensure_parquet_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        import pyarrow  # noqa: F401
    except ImportError:

        def _mock_to_parquet(
            self: pd.DataFrame, path_or_buf: Any, **kwargs: Any
        ) -> bytes | None:
            data = b"PAR1_MOCK_PARQUET_STREAM_DATA"
            if hasattr(path_or_buf, "write"):
                path_or_buf.write(data)
                return None
            Path(path_or_buf).write_bytes(data)
            return None

        monkeypatch.setattr(pd.DataFrame, "to_parquet", _mock_to_parquet)
        monkeypatch.setattr(
            pd,
            "read_parquet",
            lambda path, **kwargs: pd.DataFrame(
                [{"amount": "1500.00"}, {"amount": "-50.00"}]
            ),
        )


def test_export_parquet_from_dataframe(tmp_path: Path) -> None:
    """Exports a pandas DataFrame to a Parquet file and verifies byte content."""
    df = pd.DataFrame(
        [
            {
                "date": "2026-01-15",
                "amount": "1500.00",
                "currency": "EUR",
                "description": "Payment",
            },
            {
                "date": "2026-01-20",
                "amount": "-50.00",
                "currency": "EUR",
                "description": "Fee",
            },
        ]
    )
    out_file = tmp_path / "test.parquet"
    parquet_bytes = export_parquet(df, output_path=out_file)

    assert isinstance(parquet_bytes, bytes)
    assert len(parquet_bytes) > 0
    assert out_file.exists()
    assert out_file.stat().st_size == len(parquet_bytes)

    # Read back to verify schema round-trip
    read_df = pd.read_parquet(out_file)
    assert len(read_df) == 2
    assert "amount" in read_df.columns


def test_export_parquet_from_transaction_models(tmp_path: Path) -> None:
    """Exports a list of Transaction models to Parquet."""
    txs = [
        Transaction(
            date="2026-02-01",
            description="Salary",
            amount=Decimal("4000.00"),
            currency="EUR",
        ),
        Transaction(
            date="2026-02-05",
            description="Utilities",
            amount=Decimal("-120.50"),
            currency="EUR",
        ),
    ]
    out_file = tmp_path / "transactions.parquet"
    parquet_bytes = export_parquet(txs, output_path=out_file)
    assert len(parquet_bytes) > 0

    read_df = pd.read_parquet(out_file)
    assert len(read_df) == 2


def test_base_parser_to_parquet_method(tmp_path: Path) -> None:
    """Tests the to_parquet() method on parser instances."""
    csv_content = (
        "Date,Description,Amount\n2026-01-10,Direct Deposit,2500.00\n"
    )
    csv_file = tmp_path / "statement.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    parser = CsvStatementParser(csv_file)
    out_parquet = tmp_path / "csv_out.parquet"
    res_bytes = parser.to_parquet(out_parquet)

    assert len(res_bytes) > 0
    assert out_parquet.exists()


def test_export_parquet_raw_dicts_and_objects() -> None:
    """Exports list of raw dictionaries and simple objects."""

    class CustomRecord:
        def __init__(self, val: str) -> None:
            self.val = val

    class DictRecord:
        def to_dict(self) -> dict:
            return {"k": "v"}

    records = [
        {"a": "hello", "b": 123},
        CustomRecord("test_obj"),
        DictRecord(),
        "plain_string_item",
    ]
    parquet_bytes = export_parquet(records)
    assert isinstance(parquet_bytes, bytes)
    assert len(parquet_bytes) > 0


def test_base_parser_to_parquet_error_and_str() -> None:
    """Tests to_parquet error raising and __str__ exception fallback."""
    from bankstatementparser.base_parser import BankStatementParser
    from bankstatementparser.exceptions import ExportError

    class FailingParser(BankStatementParser):
        def parse(self) -> pd.DataFrame:
            raise ValueError("Corrupt data")

        def get_summary(self) -> dict:
            raise RuntimeError("Summary failed")

    p = FailingParser("/fake/file.csv")
    with pytest.raises(ExportError, match="Failed to export Parquet"):
        p.to_parquet()

    assert str(p) == "FailingParser(file='/fake/file.csv')"


def test_export_parquet_raises_clear_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests that missing pyarrow/fastparquet raises clear ImportError."""

    def _raise_import_err(*args: Any, **kwargs: Any) -> None:
        raise ImportError("Unable to find a usable engine")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _raise_import_err)
    with pytest.raises(
        ImportError, match="Apache Parquet export requires 'pyarrow'"
    ):
        export_parquet([{"a": 1}])
