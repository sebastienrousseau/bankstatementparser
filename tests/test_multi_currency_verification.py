# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for multi-currency balance verification (#v0.0.8)."""

from __future__ import annotations

from decimal import Decimal

from bankstatementparser import Transaction
from bankstatementparser.hybrid.verification import (
    VerificationStatus,
    verify_balance_multi_currency,
)


def _tx(amount: str, currency: str, day: str = "2026-04-01") -> Transaction:
    return Transaction(
        amount=Decimal(amount),
        currency=currency,
        booking_date=day,  # type: ignore[arg-type]
        description="x",
    )


def test_groups_by_currency_and_verifies_independently() -> None:
    txs = [
        _tx("100.00", "GBP"),
        _tx("-30.00", "GBP"),
        _tx("200.00", "EUR"),
        _tx("-50.00", "EUR"),
    ]
    results = verify_balance_multi_currency(
        txs,
        balances={
            "GBP": (Decimal("500"), Decimal("570")),
            "EUR": (Decimal("1000"), Decimal("1150")),
        },
    )
    assert "GBP" in results
    assert "EUR" in results
    assert results["GBP"].status is VerificationStatus.VERIFIED
    assert results["EUR"].status is VerificationStatus.VERIFIED


def test_discrepancy_in_one_currency_does_not_affect_other() -> None:
    txs = [
        _tx("100.00", "GBP"),
        _tx("200.00", "EUR"),
    ]
    results = verify_balance_multi_currency(
        txs,
        balances={
            "GBP": (Decimal("500"), Decimal("600")),
            "EUR": (Decimal("1000"), Decimal("9999")),  # wrong
        },
    )
    assert results["GBP"].status is VerificationStatus.VERIFIED
    assert results["EUR"].status is VerificationStatus.DISCREPANCY


def test_missing_currency_balance_returns_failed() -> None:
    txs = [_tx("100.00", "GBP"), _tx("50.00", "USD")]
    results = verify_balance_multi_currency(
        txs,
        balances={"GBP": (Decimal("0"), Decimal("100"))},
    )
    assert results["GBP"].status is VerificationStatus.VERIFIED
    assert results["USD"].status is VerificationStatus.FAILED


def test_none_currency_grouped_as_unknown() -> None:
    tx = Transaction(amount=Decimal("10.00"), description="x")
    results = verify_balance_multi_currency([tx])
    assert "UNKNOWN" in results
    assert results["UNKNOWN"].status is VerificationStatus.FAILED


def test_no_balances_returns_failed_for_all() -> None:
    txs = [_tx("100.00", "GBP"), _tx("50.00", "EUR")]
    results = verify_balance_multi_currency(txs)
    assert results["GBP"].status is VerificationStatus.FAILED
    assert results["EUR"].status is VerificationStatus.FAILED


def test_empty_input_returns_empty_dict() -> None:
    assert verify_balance_multi_currency([]) == {}


def test_currency_keys_are_uppercase() -> None:
    txs = [_tx("10.00", "gbp")]
    results = verify_balance_multi_currency(
        txs,
        balances={"GBP": (Decimal("0"), Decimal("10"))},
    )
    assert "GBP" in results
    assert "gbp" not in results
