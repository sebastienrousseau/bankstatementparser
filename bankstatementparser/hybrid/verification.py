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

"""Golden Rule balance verification.

If ``opening + credits - debits != closing`` the statement is flagged
as ``Discrepancy`` (or ``Failed`` when balances are missing). This is
the single most important integrity check in the hybrid pipeline.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from ..transaction_models import Transaction


class VerificationStatus(str, Enum):
    """Verification outcome for a parsed statement."""

    VERIFIED = "verified"
    DISCREPANCY = "discrepancy"
    FAILED = "failed"


@dataclass(frozen=True)
class BalanceVerification:
    """Result of running the Golden Rule balance check."""

    status: VerificationStatus
    opening_balance: Optional[Decimal]
    closing_balance: Optional[Decimal]
    total_credits: Decimal
    total_debits: Decimal
    expected_delta: Optional[Decimal]
    actual_delta: Decimal
    discrepancy: Optional[Decimal]
    message: str


def verify_balance(
    transactions: Iterable[Transaction],
    *,
    opening_balance: Optional[Decimal],
    closing_balance: Optional[Decimal],
    tolerance: Decimal = Decimal("0.01"),
) -> BalanceVerification:
    """Run the Golden Rule on a transaction set.

    Args:
        transactions: Iterable of normalized transactions. Debits are
            represented as negative amounts and credits as positive.
        opening_balance: Statement opening balance, or ``None`` if the
            source did not provide it.
        closing_balance: Statement closing balance, or ``None``.
        tolerance: Allowed absolute drift before flagging a
            discrepancy. Defaults to one cent.

    Returns:
        A :class:`BalanceVerification` describing the outcome. The
        ``status`` is ``FAILED`` only when the rule cannot be applied
        (missing balances), not when it disagrees.
    """
    credits = Decimal("0")
    debits = Decimal("0")
    for tx in transactions:
        if tx.amount >= 0:
            credits += tx.amount
        else:
            debits += -tx.amount

    actual_delta = credits - debits

    if opening_balance is None or closing_balance is None:
        return BalanceVerification(
            status=VerificationStatus.FAILED,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            total_credits=credits,
            total_debits=debits,
            expected_delta=None,
            actual_delta=actual_delta,
            discrepancy=None,
            message=(
                "Cannot verify: missing opening or closing balance"
            ),
        )

    expected_delta = closing_balance - opening_balance
    discrepancy = actual_delta - expected_delta
    if abs(discrepancy) <= tolerance:
        return BalanceVerification(
            status=VerificationStatus.VERIFIED,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            total_credits=credits,
            total_debits=debits,
            expected_delta=expected_delta,
            actual_delta=actual_delta,
            discrepancy=discrepancy,
            message="Balance verified within tolerance",
        )

    return BalanceVerification(
        status=VerificationStatus.DISCREPANCY,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        total_credits=credits,
        total_debits=debits,
        expected_delta=expected_delta,
        actual_delta=actual_delta,
        discrepancy=discrepancy,
        message=(
            f"Balance mismatch: expected delta {expected_delta}, "
            f"actual {actual_delta} (off by {discrepancy})"
        ),
    )
