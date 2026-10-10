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

"""MT940 bank statement parser with reversal and multiline narrative support."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pandas as pd

from ..base_parser import BankStatementParser, _single_summary
from ..input_validator import ValidationError
from ..record_types import SummaryRecord, TransactionRecord
from .common import _read_validated_text, _require_amount


class _Mt940State:
    """Internal state holder for MT940 streaming line parser."""

    def __init__(self, initial_summary: SummaryRecord) -> None:
        """Initialize parser state with a default empty summary."""
        self.summary: SummaryRecord = initial_summary
        self.current: TransactionRecord | None = None
        self.in_86: bool = False
        self.has_scope: bool = False


class Mt940Parser(BankStatementParser):
    """Parse MT940 bank statement files with reversal and multiline support."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and read the MT940 file."""
        super().__init__(file_name)
        self._path, self._text = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None
        self._summaries: list[SummaryRecord] = []

    @staticmethod
    def _empty_summary() -> SummaryRecord:
        """Create an independent statement scope with unknown balances."""
        return {
            "account_id": None,
            "currency": None,
            "statement_date": None,
            "transaction_count": 0,
            "total_amount": Decimal("0"),
            "opening_balance": None,
            "closing_balance": None,
        }

    @staticmethod
    def _parse_balance_line(line: str, summary: SummaryRecord) -> None:
        """Parse opening or closing balance line and validate currency/balance."""
        match = re.fullmatch(
            r":(60F|60M|62F|62M):([CD])(\d{6})([A-Z]{3})([0-9,]+)",
            line,
        )
        if match is None:
            raise ValidationError("Malformed MT940 balance line")
        currency = match.group(4)
        if summary["currency"] not in (None, currency):
            raise ValidationError("Conflicting MT940 statement currencies")
        summary["currency"] = currency
        amount = _require_amount(match.group(5), context="MT940 balance")
        if match.group(2) == "D":
            amount = -amount
        balance_key: Literal["opening_balance", "closing_balance"] = (
            "opening_balance"
            if match.group(1).startswith("60")
            else "closing_balance"
        )
        if summary[balance_key] not in (None, amount):
            raise ValidationError("Conflicting MT940 statement balances")
        summary[balance_key] = amount
        summary["statement_date"] = (
            datetime.strptime(match.group(3), "%y%m%d").date().isoformat()
        )

    @staticmethod
    def _parse_transaction_line(
        line: str, summary: SummaryRecord
    ) -> TransactionRecord:
        """Parse an MT940 :61: transaction line into a TransactionRecord."""
        match = re.fullmatch(
            r":61:(\d{6})(?:\d{4})?(RC|RD|EC|ED|C|D)[A-Z]?([0-9,]+)(.*)",
            line,
        )
        if match is None:
            raise ValidationError("Malformed MT940 :61: transaction line")
        # Debit and credit reversals have the opposite cash direction.
        sign = (
            Decimal("-1")
            if match.group(2) in {"D", "RC", "ED"}
            else Decimal("1")
        )
        amount = sign * _require_amount(
            match.group(3), context="MT940 :61: line"
        )
        return {
            "date": datetime.strptime(match.group(1), "%y%m%d")
            .date()
            .isoformat(),
            "amount": amount,
            "transaction_id": match.group(4).strip() or None,
            "account_id": summary["account_id"],
            "currency": summary["currency"],
            "description": None,
        }

    @staticmethod
    def _append_narrative_line(line: str, current: TransactionRecord) -> bool:
        """Append a continuation line to narrative, returning whether still in narrative."""
        if re.match(
            r"^:[0-9]{2}[A-Z]?:", line
        ) is None and not line.startswith("-"):
            desc = current.get("description") or ""
            current["description"] = (desc + " " + line).strip() or None
            return True
        return False

    def _check_new_scope(
        self,
        line: str,
        state: _Mt940State,
        summaries: list[SummaryRecord],
    ) -> None:
        """Check if line starts a new scope and save previous summary."""
        if line.startswith(":20:") or (
            line.startswith(":25:") and state.summary["account_id"] is not None
        ):
            if state.has_scope:
                summaries.append(state.summary)
            state.summary = self._empty_summary()
            state.current = None
            state.in_86 = False
            state.has_scope = True

    @staticmethod
    def _handle_header_tag(
        line: str,
        state: _Mt940State,
    ) -> bool:
        """Process MT940 header tags (:20:, :25:, :28C:)."""
        if line.startswith(":20:"):
            state.summary["message_id"] = line[4:].strip() or None
            return True
        if line.startswith(":25:"):
            state.has_scope = True
            state.in_86 = False
            state.current = None
            state.summary["account_id"] = line[4:].strip() or None
            return True
        if line.startswith(":28C:"):
            state.summary["statement_id"] = line[5:].strip() or None
            state.current = None
            state.in_86 = False
            return True
        return False

    def _handle_statement_body_tag(
        self,
        line: str,
        state: _Mt940State,
        rows: list[TransactionRecord],
    ) -> bool:
        """Process MT940 balance (:60/:62) and transaction (:61:) tags."""
        if line.startswith((":60F:", ":60M:", ":62F:", ":62M:")):
            state.has_scope = True
            state.in_86 = False
            state.current = None
            self._parse_balance_line(line, state.summary)
            return True
        if line.startswith(":61:"):
            state.has_scope = True
            state.in_86 = False
            current = self._parse_transaction_line(line, state.summary)
            state.current = current
            rows.append(current)
            count = state.summary["transaction_count"]
            state.summary["transaction_count"] = count + 1
            total = state.summary["total_amount"]
            amount: Decimal = current["amount"]  # type: ignore[assignment]
            state.summary["total_amount"] = total + amount
            return True
        return False

    def _handle_narrative_tag(
        self,
        line: str,
        state: _Mt940State,
    ) -> None:
        """Process MT940 narrative (:86:) and continuation lines."""
        if line.startswith(":86:"):
            if state.current is not None:
                state.current["description"] = line[4:].strip() or None
                state.in_86 = True
            return
        if state.current is not None and not self._append_narrative_line(
            line, state.current
        ):
            state.in_86 = False
            state.current = None

    def _process_line(
        self,
        line: str,
        state: _Mt940State,
        rows: list[TransactionRecord],
        summaries: list[SummaryRecord],
    ) -> None:
        """Process a single MT940 line updating parser state and parsed rows."""
        self._check_new_scope(line, state, summaries)
        if self._handle_header_tag(line, state):
            return
        if self._handle_statement_body_tag(line, state, rows):
            return
        if line.startswith(":86:") or state.in_86:
            self._handle_narrative_tag(line, state)

    def parse(self) -> pd.DataFrame:
        """Parse statement-scoped transactions, signed balances and reversals.

        Two-digit dates use Python's explicit 1969-2068 interpretation.
        RC reverses a credit (negative); RD reverses a debit (positive).
        """
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        rows: list[TransactionRecord] = []
        summaries: list[SummaryRecord] = []
        state = _Mt940State(self._empty_summary())

        for raw_line in self._text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            self._process_line(line, state, rows, summaries)

        summaries.append(state.summary)
        self._summaries = summaries
        self._parsed_df = pd.DataFrame(rows)
        return self._parsed_df.copy()

    def get_summaries(self) -> list[SummaryRecord]:
        """Return independent MT940 statement totals and signed balances."""
        self.parse()
        return [summary.copy() for summary in self._summaries]

    def get_summary(self) -> SummaryRecord:
        """Return one MT940 account/currency scope, rejecting mixed files."""
        return _single_summary(self.get_summaries())
