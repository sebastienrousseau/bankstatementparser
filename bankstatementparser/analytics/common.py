# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Common extraction and attribute resolution utilities for analytics."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .._amounts import iso_decimal

_ALIASES: dict[str, tuple[str, ...]] = {
    "amount": ("Amount", "InstdAmt"),
    "currency": ("Currency",),
    "booking_date": ("BookgDt",),
    "value_date": ("ValDt",),
    "description": ("Description", "Reference", "RmtInf"),
    "credit_debit": ("DrCr",),
    "account_id": ("AccountId", "DbtrIBAN"),
}

_CREDIT_DIRECTIONS = frozenset(("CRDT", "CREDIT", "C", "CR"))
_DEBIT_DIRECTIONS = frozenset(("DBIT", "DEBIT", "D", "DR"))


def _extract_date(val: Any) -> date | None:
    """Parse arbitrary date object or string into a datetime.date."""
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        val_clean = val.strip()[:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(val_clean, fmt).date()
            except ValueError:
                continue
    return None


def _extract_amount(val: Any) -> Decimal:
    """Convert amount attribute to Decimal."""
    return iso_decimal(
        str(val).strip().replace(",", ".").replace(" ", ""),
        context="analytics amount",
    )


def _get_dict_value(obj: dict[str, Any], key: str) -> Any:
    """Retrieve non-empty value from a dictionary by key."""
    if key in obj and obj[key] not in (None, ""):
        return obj[key]
    return None


def _get_attr(obj: Any, *keys: str, default: Any = None) -> Any:
    """Retrieve attribute or dict key across Transaction or dict instances."""
    expanded = [
        alias for key in keys for alias in (key, *_ALIASES.get(key, ()))
    ]
    for key in expanded:
        if isinstance(obj, dict):
            val = _get_dict_value(obj, key)
            if val is not None:
                return val
        elif hasattr(obj, key):
            val = getattr(obj, key)
            if val is not None:
                return val
    return default


def _amount_and_direction(tx: Any) -> tuple[Decimal, bool]:
    """Resolve explicit bank direction before falling back to amount sign."""
    amount = _extract_amount(_get_attr(tx, "amount", "amt", default=None))
    direction = str(
        _get_attr(tx, "credit_debit", "drcr", "type", default="")
    ).upper()
    if direction in _CREDIT_DIRECTIONS:
        return amount, True
    if direction in _DEBIT_DIRECTIONS:
        return amount, False
    return amount, amount >= 0


def _calendar_months(start: date, end: date) -> Decimal:
    """Measure an inclusive period in calendar months, prorating edge months."""
    cursor = start
    months = Decimal(0)
    while True:
        last = date(
            cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1]
        )
        stop = min(last, end)
        months += Decimal((stop - cursor).days + 1) / last.day
        if stop == end:
            return months
        cursor = date(
            cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1
        )
