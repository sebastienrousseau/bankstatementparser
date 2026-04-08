# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the Golden Rule balance verification."""

from __future__ import annotations

from decimal import Decimal

from bankstatementparser import Transaction
from bankstatementparser.hybrid.verification import (
    VerificationStatus,
    verify_balance,
)


def _tx(amount: str) -> Transaction:
    return Transaction(amount=Decimal(amount))


def test_verify_balance_returns_verified_when_within_tolerance() -> None:
    txs = [_tx("100.00"), _tx("-30.00"), _tx("-20.00")]
    result = verify_balance(
        txs,
        opening_balance=Decimal("500.00"),
        closing_balance=Decimal("550.00"),
    )
    assert result.status is VerificationStatus.VERIFIED
    assert result.total_credits == Decimal("100.00")
    assert result.total_debits == Decimal("50.00")
    assert result.expected_delta == Decimal("50.00")
    assert result.actual_delta == Decimal("50.00")
    assert result.discrepancy == Decimal("0.00")


def test_verify_balance_flags_discrepancy() -> None:
    txs = [_tx("100.00"), _tx("-30.00")]
    result = verify_balance(
        txs,
        opening_balance=Decimal("500.00"),
        closing_balance=Decimal("600.00"),
    )
    assert result.status is VerificationStatus.DISCREPANCY
    assert result.discrepancy is not None
    assert result.discrepancy != Decimal("0")
    assert "mismatch" in result.message


def test_verify_balance_failed_when_balances_missing() -> None:
    result = verify_balance(
        [_tx("10.00")],
        opening_balance=None,
        closing_balance=Decimal("10.00"),
    )
    assert result.status is VerificationStatus.FAILED
    assert "missing" in result.message.lower()


def test_verify_balance_failed_when_closing_missing() -> None:
    result = verify_balance(
        [_tx("10.00")],
        opening_balance=Decimal("0"),
        closing_balance=None,
    )
    assert result.status is VerificationStatus.FAILED
