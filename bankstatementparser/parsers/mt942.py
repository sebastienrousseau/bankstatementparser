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

"""MT942 interim bank transaction report parser engine."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..base_parser import BankStatementParser, _single_summary
from ..input_validator import ValidationError
from ..record_types import SummaryRecord, TransactionRecord
from .common import _read_validated_text, _require_amount


class _Mt942State:
    """Internal state holder for MT942 streaming line parser."""

    def __init__(self, initial_summary: SummaryRecord) -> None:
        """Initialize parser state with a default empty summary."""
        self.summary: SummaryRecord = initial_summary
        self.current: TransactionRecord | None = None
        self.in_86: bool = False
        self.has_scope: bool = False


class Mt942Parser(BankStatementParser):
    """Parse SWIFT MT942 interim transaction reports with streaming support."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and read the MT942 interim statement file."""
        super().__init__(file_name)
        self._path, self._text = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None
        self._summaries: list[SummaryRecord] = []

    @staticmethod
    def _empty_summary() -> SummaryRecord:
        """Create an independent MT942 interim statement summary scope."""
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
    def _parse_floor_limit(line: str, summary: SummaryRecord) -> None:
        """Parse :34F: floor limit indicator and set scope currency."""
        match = re.fullmatch(r":34F:([A-Z]{3})([CD])?([0-9,]+)", line)
        if match is None:
            raise ValidationError(f"Malformed MT942 :34F: line: {line}")
        currency = match.group(1)
        if summary["currency"] not in (None, currency):
            raise ValidationError("Conflicting MT942 statement currency")
        summary["currency"] = currency
        floor_amt = _require_amount(
            match.group(3), context="MT942 floor limit"
        )
        if match.group(2) == "D":
            floor_amt = -floor_amt
        summary["opening_balance"] = floor_amt

    @staticmethod
    def _parse_datetime_indication(line: str, summary: SummaryRecord) -> None:
        """Parse :13D: date/time indication and record statement timestamp."""
        match = re.fullmatch(r":13D:(\d{6})(\d{4})([+-]\d{4})?", line)
        if match is None:
            raise ValidationError(f"Malformed MT942 :13D: line: {line}")
        date_str = match.group(1)
        summary["statement_date"] = (
            datetime.strptime(date_str, "%y%m%d").date().isoformat()
        )

    @staticmethod
    def _parse_transaction_line(
        line: str, summary: SummaryRecord
    ) -> TransactionRecord:
        """Parse an MT942 :61: interim transaction line into a TransactionRecord."""
        match = re.fullmatch(
            r":61:(\d{6})(?:\d{4})?(RC|RD|EC|ED|C|D)[A-Z]?([0-9,]+)(.*)",
            line,
        )
        if match is None:
            raise ValidationError("Malformed MT942 :61: transaction line")
        sign = (
            Decimal("-1")
            if match.group(2) in {"D", "RC", "ED"}
            else Decimal("1")
        )
        amount = sign * _require_amount(
            match.group(3), context="MT942 :61: line"
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

    def _check_new_scope(
        self,
        line: str,
        state: _Mt942State,
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
    def _handle_header_tag(line: str, state: _Mt942State) -> bool:
        """Process MT942 header tags (:20:, :21:, :25:, :28C:)."""
        if line.startswith(":20:"):
            state.summary["message_id"] = line[4:].strip() or None
            return True
        if line.startswith(":21:"):
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

    def _handle_body_tag(
        self,
        line: str,
        state: _Mt942State,
        rows: list[TransactionRecord],
    ) -> bool:
        """Process MT942 control (:34F:, :13D:) and transaction (:61:) tags."""
        if line.startswith(":34F:"):
            state.has_scope = True
            state.in_86 = False
            state.current = None
            self._parse_floor_limit(line, state.summary)
            return True
        if line.startswith(":13D:"):
            self._parse_datetime_indication(line, state.summary)
            return True
        if line.startswith(":61:"):
            state.has_scope = True
            state.in_86 = False
            current = self._parse_transaction_line(line, state.summary)
            state.current = current
            rows.append(current)
            state.summary["transaction_count"] += 1
            state.summary["total_amount"] += current["amount"]  # type: ignore[operator]
            return True
        return False

    @staticmethod
    def _append_narrative(line: str, current: TransactionRecord) -> bool:
        """Append continuation line to narrative, returning whether still active."""
        if re.match(
            r"^:[0-9]{2}[A-Z]?:", line
        ) is None and not line.startswith("-"):
            desc = current.get("description") or ""
            current["description"] = (desc + " " + line).strip() or None
            return True
        return False

    def _process_line(
        self,
        line: str,
        state: _Mt942State,
        rows: list[TransactionRecord],
        summaries: list[SummaryRecord],
    ) -> None:
        """Process a single MT942 line according to SWIFT interim report grammar."""
        self._check_new_scope(line, state, summaries)
        if self._handle_header_tag(line, state):
            return
        if self._handle_body_tag(line, state, rows):
            return
        if line.startswith(":86:"):
            state.in_86 = True
            if state.current is not None:
                state.current["description"] = line[4:].strip() or None
            return
        if state.in_86 and state.current is not None:
            state.in_86 = self._append_narrative(line, state.current)

    def parse_streaming(self) -> list[TransactionRecord]:
        """Stream parsed records as a list of TransactionRecord dictionaries."""
        rows: list[TransactionRecord] = []
        summaries: list[SummaryRecord] = []
        state = _Mt942State(self._empty_summary())

        for raw_line in self._text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("-"):
                continue
            self._process_line(line, state, rows, summaries)

        if state.has_scope:
            summaries.append(state.summary)

        # Reconcile missing currency and accounts from scope
        for row in rows:
            if row["currency"] is None and state.summary["currency"]:
                row["currency"] = state.summary["currency"]
            if row["account_id"] is None and state.summary["account_id"]:
                row["account_id"] = state.summary["account_id"]

        self._summaries = summaries or [state.summary]
        return rows

    def parse(self) -> pd.DataFrame:
        """Parse the MT942 file into a canonical pandas DataFrame."""
        if self._parsed_df is not None:
            return self._parsed_df
        rows = self.parse_streaming()
        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame(
                columns=[
                    "date",
                    "amount",
                    "transaction_id",
                    "account_id",
                    "currency",
                    "description",
                ]
            )
        self._parsed_df = df
        return df

    def get_summaries(self) -> list[SummaryRecord]:
        """Return summary records for all scopes present in the statement."""
        if not self._summaries:
            self.parse_streaming()
        return self._summaries

    def get_summary(self) -> SummaryRecord:
        """Return the single summary record for the statement."""
        return _single_summary(self.get_summaries())
