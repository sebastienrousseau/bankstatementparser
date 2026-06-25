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
    verify_continuity,
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


def test_verify_balance_unverifiable_when_balances_missing() -> None:
    result = verify_balance(
        [_tx("10.00")],
        opening_balance=None,
        closing_balance=Decimal("10.00"),
    )
    assert result.status is VerificationStatus.UNVERIFIABLE
    assert "missing" in result.message.lower()


def test_verify_balance_unverifiable_when_closing_missing() -> None:
    result = verify_balance(
        [_tx("10.00")],
        opening_balance=Decimal("0"),
        closing_balance=None,
    )
    assert result.status is VerificationStatus.UNVERIFIABLE


def test_verify_continuity_verified_when_chain_matches() -> None:
    result = verify_continuity(
        [
            ("jan.xml", Decimal("100"), Decimal("250")),
            ("feb.xml", Decimal("250"), Decimal("300")),
            ("mar.xml", Decimal("300.005"), Decimal("180")),
        ]
    )
    assert result.status is VerificationStatus.VERIFIED
    assert result.checked_links == 2
    assert result.unchecked_links == 0
    assert result.breaks == ()
    assert "3 statements" in result.message


def test_verify_continuity_reports_break_with_gap() -> None:
    result = verify_continuity(
        [
            ("jan.xml", Decimal("100"), Decimal("250")),
            ("feb.xml", Decimal("400"), Decimal("500")),
        ]
    )
    assert result.status is VerificationStatus.DISCREPANCY
    assert result.checked_links == 1
    assert len(result.breaks) == 1
    brk = result.breaks[0]
    assert brk.previous_label == "jan.xml"
    assert brk.next_label == "feb.xml"
    assert brk.previous_closing == Decimal("250")
    assert brk.next_opening == Decimal("400")
    assert brk.gap == Decimal("150")
    assert "jan.xml closed at 250" in result.message


def test_verify_continuity_break_takes_precedence_over_missing() -> None:
    result = verify_continuity(
        [
            ("jan.xml", Decimal("100"), None),
            ("feb.xml", Decimal("250"), Decimal("300")),
            ("mar.xml", Decimal("999"), Decimal("1000")),
        ]
    )
    assert result.status is VerificationStatus.DISCREPANCY
    assert result.checked_links == 1
    assert result.unchecked_links == 1
    assert len(result.breaks) == 1


def test_verify_continuity_unverifiable_when_balance_missing() -> None:
    result = verify_continuity(
        [
            ("jan.xml", Decimal("100"), Decimal("250")),
            ("feb.xml", None, Decimal("300")),
        ]
    )
    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.unchecked_links == 1
    assert "1 of 1 links missing a balance" in result.message


def test_verify_continuity_needs_at_least_two_statements() -> None:
    result = verify_continuity([("jan.xml", Decimal("1"), Decimal("2"))])
    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.checked_links == 0
    assert "at least two statements" in result.message


def test_verify_continuity_custom_tolerance() -> None:
    statements = [
        ("jan.xml", Decimal("100"), Decimal("250")),
        ("feb.xml", Decimal("251"), Decimal("300")),
    ]
    strict = verify_continuity(statements)
    assert strict.status is VerificationStatus.DISCREPANCY
    relaxed = verify_continuity(statements, tolerance=Decimal("1"))
    assert relaxed.status is VerificationStatus.VERIFIED
