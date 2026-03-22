# Copyright (C) 2023 Sebastien Rousseau.
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

"""Deterministic transaction models used across parser outputs."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


def _coerce_decimal(value: Any) -> Decimal:
    text = str(value).strip()
    if not text:
        raise ValueError("amount is required")
    return Decimal(text)


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10:
        text = text[:10]

    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError as exc:
        raise ValueError(f"unsupported date format: {value}") from exc


def normalize_description(value: str | None) -> str:
    if value is None:
        return ""
    collapsed = re.sub(r"\s+", " ", value).strip().lower()
    return re.sub(r"[^a-z0-9 ]+", "", collapsed)


def _first_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


class Transaction(BaseModel):
    """Normalized transaction model for deterministic downstream logic."""

    model_config = ConfigDict(frozen=True)

    account_id: Optional[str] = None
    currency: Optional[str] = None
    amount: Decimal
    booking_date: Optional[date] = None
    value_date: Optional[date] = None
    description: Optional[str] = None
    normalized_description: str = Field(default="")
    reference: Optional[str] = None
    transaction_id: Optional[str] = None
    counterparty: Optional[str] = None
    source: Optional[str] = None
    source_index: Optional[int] = None

    @classmethod
    def from_record(
        cls,
        record: dict[str, Any],
        *,
        source: str | None = None,
        source_index: int | None = None,
    ) -> Transaction:
        """Create a normalized transaction from parser output."""
        description = _first_value(
            record,
            "description",
            "Description",
            "RmtInf",
            "Reference",
            "reference",
            "Memo",
            "memo",
            "Name",
            "CdtrNm",
        )
        reference = _first_value(
            record,
            "Reference",
            "reference",
            "RmtInf",
            "transaction_id",
            "transactionId",
            "EndToEndId",
            "FITID",
        )
        counterparty = _first_value(
            record,
            "Creditor",
            "Debtor",
            "CdtrNm",
            "Name",
            "payee",
            "counterparty",
        )
        amount = _coerce_decimal(
            _first_value(record, "Amount", "amount", "InstdAmt")
        )
        account_id = _first_value(
            record,
            "AccountId",
            "account_id",
            "DbtrIBAN",
            "CreditorAccount",
        )
        currency = _first_value(record, "Currency", "currency")

        return cls(
            account_id=str(account_id)
            if account_id is not None
            else None,
            currency=str(currency).upper()
            if currency is not None
            else None,
            amount=amount,
            booking_date=_parse_date(
                _first_value(record, "BookgDt", "booking_date", "date")
            ),
            value_date=_parse_date(
                _first_value(record, "ValDt", "value_date", "date")
            ),
            description=str(description)
            if description is not None
            else None,
            normalized_description=normalize_description(
                str(description) if description is not None else None
            ),
            reference=str(reference) if reference is not None else None,
            transaction_id=(
                str(
                    _first_value(
                        record,
                        "transaction_id",
                        "TransactionId",
                        "FITID",
                        "EndToEndId",
                    )
                )
                if _first_value(
                    record,
                    "transaction_id",
                    "TransactionId",
                    "FITID",
                    "EndToEndId",
                )
                is not None
                else None
            ),
            counterparty=(
                str(counterparty) if counterparty is not None else None
            ),
            source=source,
            source_index=source_index,
        )

    def amount_key(self) -> str:
        """Return a stable amount key for hashing and comparisons."""
        return format(self.amount.normalize(), "f")
