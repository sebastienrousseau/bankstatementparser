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

"""Strict Decimal parsing for monetary amounts.

Money is never represented as a float in this library: binary
floats cannot represent common decimal fractions (``0.1 + 0.2 !=
0.3``), and reconciliation against bank-stated balances must be
exact. Parsers convert source-text amounts straight to
:class:`decimal.Decimal`, and a value that cannot be parsed raises
instead of silently becoming ``0.0``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional


def iso_decimal(text: Optional[str], *, context: str) -> Decimal:
    """Parse an ISO 20022 amount string into a finite Decimal.

    Args:
        text: The raw element text (e.g. ``"1234.56"``).
        context: Human-readable location for the error message,
            e.g. ``"balance element"``.

    Raises:
        ValueError: If the text is missing, empty, or not a finite
            decimal number. A garbled amount must fail loudly — a
            silent ``0.0`` fallback corrupts every downstream sum
            and balance check.
    """
    if text is None or not text.strip():
        raise ValueError(f"Missing amount in {context}")
    try:
        value = Decimal(text.strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount {text!r} in {context}") from exc
    if not value.is_finite():
        raise ValueError(f"Non-finite amount {text!r} in {context}")
    return value
