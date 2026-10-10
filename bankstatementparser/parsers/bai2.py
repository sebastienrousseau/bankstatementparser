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

"""BAI2 (Bank Administration Institute Standard 2) statement parser."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from ..base_parser import BankStatementParser, _single_summary
from ..record_types import SummaryRecord, TransactionRecord
from ..transaction_models import Transaction
from .common import _read_validated_text, _require_amount


def _parse_bai2_date(date_str: str) -> date | None:
    """Parse YYMMDD or YYYYMMDD into a datetime.date."""
    cleaned = date_str.strip()
    if not cleaned:
        return None
    for fmt in ("%y%m%d", "%Y%m%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_bai2_amount(raw: str, currency: str | None) -> Decimal:
    """Parse integer cents or decimal string into Decimal amount."""
    val = raw.strip()
    if not val:
        return Decimal("0.00")
    if "." in val:
        return Decimal(val)
    # Default 2 decimal places for standard currencies
    return Decimal(val) / Decimal("100")


class _Bai2State:
    """Internal mutable state during BAI2 streaming line traversal."""

    def __init__(self) -> None:
        """Initialize parser state with empty records and tracking."""
        self.file_sender: str | None = None
        self.file_receiver: str | None = None
        self.group_currency: str | None = None
        self.as_of_date: date | None = None
        self.account_id: str | None = None
        self.account_currency: str | None = None
        self.opening_balance: Decimal | None = None
        self.closing_balance: Decimal | None = None
        self.last_record_type: str | None = None
        self.last_tx: dict[str, Any] | None = None
        self.summaries: list[SummaryRecord] = []
        self.current_summary: SummaryRecord | None = None


class Bai2Parser(BankStatementParser):
    """Parse BAI2 cash management statement files into standardized records."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and read BAI2 file content."""
        super().__init__(file_name)
        self._path, self._text = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None
        self._summaries: list[SummaryRecord] = []
        self._transactions: list[Transaction] = []

    def _reset_account_state(self, state: _Bai2State) -> None:
        """Finalize prior account summary if any before starting new scope."""
        if state.current_summary is not None:
            state.summaries.append(state.current_summary)
        state.opening_balance = None
        state.closing_balance = None
        state.last_tx = None

    def _handle_header_01(self, parts: list[str], state: _Bai2State) -> None:
        """Parse Record 01: File Header."""
        if len(parts) >= 3:
            state.file_sender = parts[1]
            state.file_receiver = parts[2]
        state.last_record_type = "01"

    def _handle_header_02(self, parts: list[str], state: _Bai2State) -> None:
        """Parse Record 02: Group Header."""
        if len(parts) >= 5:
            state.as_of_date = _parse_bai2_date(parts[4])
        if len(parts) >= 7 and parts[6].strip():
            state.group_currency = parts[6].strip()
        state.last_record_type = "02"

    def _handle_account_03(self, parts: list[str], state: _Bai2State) -> None:
        """Parse Record 03: Account Identifier and summary balances."""
        self._reset_account_state(state)
        state.account_id = parts[1].strip() if len(parts) > 1 else None
        curr = parts[2].strip() if len(parts) > 2 else ""
        state.account_currency = curr or state.group_currency or "USD"

        # Check for status/summary codes in fields 3+
        idx = 3
        while idx + 1 < len(parts):
            code = parts[idx].strip()
            amt_str = parts[idx + 1].strip()
            if code in ("010", "040") and amt_str:
                state.opening_balance = _parse_bai2_amount(
                    amt_str, state.account_currency
                )
            elif code in ("015", "045") and amt_str:
                state.closing_balance = _parse_bai2_amount(
                    amt_str, state.account_currency
                )
            idx += 4  # type code, amount, item count, funds type

        state.current_summary = {
            "account_id": state.account_id,
            "currency": state.account_currency,
            "statement_date": (
                state.as_of_date.isoformat() if state.as_of_date else None
            ),
            "transaction_count": 0,
            "total_amount": Decimal("0.00"),
            "opening_balance": state.opening_balance,
            "closing_balance": state.closing_balance,
        }
        state.last_record_type = "03"

    def _handle_detail_16(
        self, parts: list[str], state: _Bai2State
    ) -> Transaction | None:
        """Parse Record 16: Transaction Detail."""
        if len(parts) < 3:
            return None
        type_code = parts[1].strip()
        raw_amt = _parse_bai2_amount(parts[2], state.account_currency)

        # In BAI2: 100-399 are credits (+), 400-699 are debits (-)
        is_debit = False
        try:
            code_num = int(type_code)
            if 400 <= code_num <= 699:
                is_debit = True
        except ValueError:
            pass

        signed_amt = -abs(raw_amt) if is_debit else abs(raw_amt)
        bank_ref = (parts[4].strip() or None) if len(parts) > 4 else None
        cust_ref = (parts[5].strip() or None) if len(parts) > 5 else None
        text_desc = parts[6].strip() if len(parts) > 6 else ""

        tx = Transaction(
            account_id=state.account_id,
            currency=state.account_currency or "USD",
            amount=signed_amt,
            booking_date=state.as_of_date,
            value_date=state.as_of_date,
            description=text_desc or f"Type {type_code}",
            normalized_description=(text_desc or f"Type {type_code}").lower(),
            reference=cust_ref or bank_ref,
            transaction_id=bank_ref,
            source=str(self.file_name),
            source_method="deterministic",
        )
        if state.current_summary is not None:
            state.current_summary["transaction_count"] += 1
            state.current_summary["total_amount"] += signed_amt
        state.last_record_type = "16"
        return tx

    def _dispatch_line(
        self, parts: list[str], state: _Bai2State
    ) -> Transaction | None:
        """Route parsed line tokens to the appropriate record handler."""
        rec_type = parts[0] if parts else ""
        if rec_type == "01":
            self._handle_header_01(parts, state)
        elif rec_type == "02":
            self._handle_header_02(parts, state)
        elif rec_type == "03":
            self._handle_account_03(parts, state)
        elif rec_type == "16":
            return self._handle_detail_16(parts, state)
        elif rec_type in ("49", "98", "99"):
            state.last_record_type = rec_type
        return None

    def _iter_logical_records(self) -> Iterator[Transaction]:
        """Stream normalized transactions from BAI2 lines."""
        state = _Bai2State()
        for raw_line in self._text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith("/"):
                line = line[:-1]
            parts = [p.strip() for p in line.split(",")]
            tx = self._dispatch_line(parts, state)
            if tx is not None:
                yield tx

        if state.current_summary is not None:
            state.summaries.append(state.current_summary)
        self._summaries = state.summaries

    def parse_streaming(self) -> Iterator[TransactionRecord]:
        """Stream dictionary transactions for lightweight processing."""
        for tx in self._iter_logical_records():
            yield {
                "AccountId": tx.account_id,
                "Currency": tx.currency,
                "Amount": tx.amount,
                "BookgDt": (
                    tx.booking_date.isoformat() if tx.booking_date else None
                ),
                "ValDt": tx.value_date.isoformat() if tx.value_date else None,
                "description": tx.description,
                "Reference": tx.reference,
                "transaction_id": tx.transaction_id,
                "amount": tx.amount,
                "currency": tx.currency,
                "account_id": tx.account_id,
                "date": (
                    tx.booking_date.isoformat() if tx.booking_date else None
                ),
            }

    def parse(self) -> pd.DataFrame:
        """Parse all transactions and return as a pandas DataFrame."""
        if self._parsed_df is not None:
            return self._parsed_df

        rows = list(self.parse_streaming())
        if not rows:
            df = pd.DataFrame(
                columns=[
                    "AccountId",
                    "Currency",
                    "Amount",
                    "BookgDt",
                    "ValDt",
                    "description",
                    "Reference",
                    "transaction_id",
                ]
            )
        else:
            df = pd.DataFrame(rows)
            df["Amount"] = df["Amount"].apply(
                lambda v: _require_amount(v, context="Amount")
            )

        self._parsed_df = df
        return self._parsed_df

    def get_summary(self) -> SummaryRecord:
        """Return primary summary for single-account statements."""
        if self._parsed_df is None:
            self.parse()
        return _single_summary(self.get_summaries())

    def get_summaries(self) -> list[SummaryRecord]:
        """Return scoped summaries for all accounts in the BAI2 statement."""
        if self._parsed_df is None:
            self.parse()
        return self._summaries or [
            {
                "account_id": None,
                "currency": None,
                "statement_date": None,
                "transaction_count": 0,
                "total_amount": Decimal("0.00"),
                "opening_balance": None,
                "closing_balance": None,
            }
        ]
