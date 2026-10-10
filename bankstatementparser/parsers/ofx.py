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

"""OFX and QFX bank statement parser."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..base_parser import BankStatementParser, _single_summary
from ..record_types import SummaryRecord, TransactionRecord
from .common import _grouped_summaries, _read_validated_text, _require_amount


class OfxParser(BankStatementParser):
    """Parse OFX and QFX bank statement files."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and read the OFX/QFX file."""
        super().__init__(file_name)
        self._path, self._text = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None

    def _tag_value(self, source: str, tag: str) -> str | None:
        """Return the stripped value of an OFX/SGML tag, or None."""
        match = re.search(rf"<{tag}>([^<\r\n]+)", source, flags=re.IGNORECASE)
        if match is None:
            return None
        return match.group(1).strip()

    def _parse_transaction_block(
        self,
        block: str,
        currency: str | None,
        account_id: str | None,
    ) -> TransactionRecord:
        """Parse a single STMTTRN XML/SGML block into a TransactionRecord."""
        posted = self._tag_value(block, "DTPOSTED") or ""
        transaction_id = self._tag_value(block, "FITID")
        return {
            "date": posted[:8],
            "description": (
                self._tag_value(block, "MEMO")
                or self._tag_value(block, "NAME")
            ),
            "amount": _require_amount(
                self._tag_value(block, "TRNAMT"),
                context=f"OFX STMTTRN {transaction_id or '(no FITID)'}",
            ),
            "currency": currency,
            "account_id": account_id,
            "transaction_id": transaction_id,
            "transaction_type": self._tag_value(block, "TRNTYPE"),
        }

    def _parse_statement_body(
        self, statement: str, rows: list[TransactionRecord]
    ) -> None:
        """Parse transactions from a single statement container."""
        currency = self._tag_value(statement, "CURDEF")
        account_id = self._tag_value(statement, "ACCTID")
        blocks = re.findall(
            r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>|</BANKTRANLIST>))",
            statement,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for block in blocks:
            rows.append(
                self._parse_transaction_block(block, currency, account_id)
            )

    def parse(self) -> pd.DataFrame:
        """Parse ``<STMTTRN>`` blocks into a DataFrame."""
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        rows: list[TransactionRecord] = []
        # OFX may contain multiple bank and credit-card statements. Metadata
        # belongs to each statement container, never the entire document.
        statements = re.findall(
            r"<(STMTRS|CCSTMTRS)>(.*?)</\1>",
            self._text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for statement in [body for _, body in statements] or [self._text]:
            self._parse_statement_body(statement, rows)

        self._parsed_df = pd.DataFrame(rows)
        return self._parsed_df.copy()

    def get_summaries(self) -> list[SummaryRecord]:
        """Summarize OFX/QFX transactions by account and currency."""
        return _grouped_summaries(self.parse())

    def get_summary(self) -> SummaryRecord:
        """Return a single OFX scope, rejecting mixed account/currency totals."""
        return _single_summary(self.get_summaries())


QfxParser = OfxParser
