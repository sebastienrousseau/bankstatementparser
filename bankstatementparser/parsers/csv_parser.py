# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""CSV bank statement parser with column normalization."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..base_parser import BankStatementParser, _single_summary
from ..input_validator import ValidationError
from ..record_types import SummaryRecord
from .common import (
    CSV_COLUMN_GROUPS,
    _amount_or_zero,
    _grouped_summaries,
    _normalized_name,
    _read_validated_text,
    _require_amount,
)


class CsvStatementParser(BankStatementParser):
    """Parse bank statement CSV files with basic column normalization."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and register the CSV file for parsing."""
        super().__init__(file_name)
        self._path, _ = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None

    def _find_column(self, df: pd.DataFrame, logical_name: str) -> str | None:
        """Return the DataFrame column matching a logical name, if any."""
        candidates = CSV_COLUMN_GROUPS[logical_name]
        for column in df.columns:
            column_name = str(column)
            if _normalized_name(column_name) in candidates:
                return column_name
        return None

    def _extract_amount_series(self, raw_df: pd.DataFrame) -> pd.Series:
        """Extract net transaction amounts from amount or credit/debit columns."""
        amount_col = self._find_column(raw_df, "amount")
        if amount_col:
            return raw_df[amount_col].map(
                lambda v: _require_amount(
                    v, context=f"CSV column {amount_col!r}"
                )
            )

        credit_col = self._find_column(raw_df, "credit")
        debit_col = self._find_column(raw_df, "debit")
        if not credit_col and not debit_col:
            raise ValidationError(
                "CSV requires an amount, debit, or credit column"
            )

        zero = pd.Series([Decimal("0")] * len(raw_df), index=raw_df.index)
        credit = (
            raw_df[credit_col].map(
                lambda v: _amount_or_zero(
                    v, context=f"CSV column {credit_col!r}"
                )
            )
            if credit_col
            else zero
        )
        debit = (
            raw_df[debit_col].map(
                lambda v: _amount_or_zero(
                    v, context=f"CSV column {debit_col!r}"
                )
            )
            if debit_col
            else zero
        )
        return credit - debit

    def parse(self) -> pd.DataFrame:
        """Parse the CSV file into a normalized DataFrame."""
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        raw_df = pd.read_csv(
            self._path,
            sep=None,
            engine="python",
            dtype=str,
            keep_default_na=False,
        )
        parsed = pd.DataFrame(index=raw_df.index)

        date_col = self._find_column(raw_df, "date")
        if date_col:
            parsed["date"] = raw_df[date_col]

        desc_col = self._find_column(raw_df, "description")
        if desc_col:
            parsed["description"] = raw_df[desc_col]

        parsed["amount"] = self._extract_amount_series(raw_df)

        for logical_name in (
            "currency",
            "balance",
            "account_id",
            "transaction_id",
        ):
            source_col = self._find_column(raw_df, logical_name)
            if source_col:
                parsed[logical_name] = raw_df[source_col]

        self._parsed_df = parsed
        return self._parsed_df.copy()

    def get_summaries(self) -> list[SummaryRecord]:
        """Summarize CSV rows separately by account and currency.

        A running balance column does not establish an opening balance without
        an explicit timing convention, so opening_balance remains unknown.
        """
        return _grouped_summaries(self.parse())

    def get_summary(self) -> SummaryRecord:
        """Return a single CSV scope, or require get_summaries for mixed files."""
        return _single_summary(self.get_summaries())
