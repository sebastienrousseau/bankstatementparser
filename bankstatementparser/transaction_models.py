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

"""Deterministic transaction models used across parser outputs."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


def _coerce_decimal(value: object) -> Decimal:
    text = str(value).strip()
    if not text:
        raise ValueError("amount is required")
    return Decimal(text)


def _parse_date(value: object) -> date | None:
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


# Patterns that produce hash-noise in bank descriptions:
# fluctuating dates, times, and long numeric/alphanumeric reference IDs
# embedded in otherwise-stable merchant strings (e.g.
# "AMZN MKTPLACE 2026-04-01 #A1B2C3").
_DATE_PATTERNS = (
    re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"),  # 2026-04-01, 2026/4/1
    re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b"),  # 01/04/2026
    re.compile(r"\b\d{1,2}[-/]\d{1,2}\b"),  # 01/04
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),  # 12:49, 12:49:01
)
_LONG_ALNUM_ID = re.compile(r"\b[a-z0-9]*\d[a-z0-9]*\b")


def normalize_description(value: str | None) -> str:
    """Normalize a description for stable hashing.

    Strips date/time tokens and long alphanumeric IDs that change
    between otherwise-identical recurring charges (e.g.
    ``AMZN MKTPLACE 2026-04-01 #A1B2C3``). The goal is for two visits
    to the same merchant on different days to produce the same
    normalized form when paired with their respective dates upstream.
    """
    if value is None:
        return ""
    text = value
    for pattern in _DATE_PATTERNS:
        text = pattern.sub(" ", text)
    collapsed = re.sub(r"\s+", " ", text).strip().lower()
    stripped_ids = _LONG_ALNUM_ID.sub(" ", collapsed)
    cleaned = re.sub(r"[^a-z ]+", " ", stripped_ids)
    return re.sub(r"\s+", " ", cleaned).strip()


def _first_value(
    record: Mapping[str, object], *keys: str
) -> object | None:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


SourceMethod = Literal["deterministic", "llm"]


class BoundingBox(BaseModel):
    """Normalized rectangle locating a row in its source PDF page.

    All four coordinates are in the **0.0-1.0 range** relative to the
    rendered page they came from. This makes the model resolution-
    independent — the same row's bbox stays valid whether the user
    re-renders at 1× or 2× scale, and tooling that highlights source
    pixels in a UI (the v0.0.6 review mode, #45) doesn't need to know
    the original render dimensions.

    Convention: ``(x0, y0)`` is the top-left corner, ``(x1, y1)`` is
    the bottom-right corner. Origin is at the top-left of the page,
    matching the coordinate system every multimodal LLM I've tested
    actually uses (gpt-4o, claude-opus-4-6, qwen2-vl, minicpm-v).

    ``page_index`` is the zero-based page number within the source
    PDF — populated whenever the bbox spans a multi-page document.
    """

    model_config = ConfigDict(frozen=True)

    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    page_index: int = Field(default=0, ge=0)


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
    source_method: SourceMethod = "deterministic"
    confidence: Optional[float] = None
    # Populated by the v0.0.6 enrichment module (#44). Defaults to
    # ``None`` so the deterministic core stays opinion-free.
    category: Optional[str] = None
    # Best-effort source-text slice for v0.0.6 review mode (#45).
    # Populated by ``LLMExtractor`` via ``_slice_source_context``.
    raw_source_text: Optional[str] = None
    # Per-row bounding box from the v0.0.6 vision path (#46).
    # Populated by ``VisionExtractor`` when the multimodal model
    # returns spatial coordinates. Always ``None`` for the
    # deterministic and text-LLM paths because no spatial source
    # exists in either case.
    source_bbox: Optional[BoundingBox] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def transaction_hash(self) -> str:
        """Idempotent fingerprint of date|normalized_description|amount.

        Generated from normalized fields so the same transaction
        produces the same hash regardless of source (deterministic
        parser vs. LLM extraction). MD5 is used for a compact,
        non-cryptographic identity key.
        """
        date_part = (
            self.booking_date.isoformat()
            if self.booking_date is not None
            else (
                self.value_date.isoformat()
                if self.value_date is not None
                else ""
            )
        )
        material = "|".join(
            [
                date_part,
                self.normalized_description,
                self.amount_key(),
            ]
        )
        return hashlib.md5(  # noqa: S324
            material.encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, object],
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
