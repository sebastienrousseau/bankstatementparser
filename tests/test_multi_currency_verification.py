# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for multi-currency balance verification (#v0.0.8)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bankstatementparser import Transaction
from bankstatementparser.hybrid.verification import (
    BalanceVerification,
    VerificationStatus,
    aggregate_verifications,
    verify_balance_multi_currency,
    verify_transactions,
)


def _tx(amount: str, currency: str, day: str = "2026-04-01") -> Transaction:
    return Transaction(
        amount=Decimal(amount),
        currency=currency,
        booking_date=day,  # type: ignore[arg-type]
        description="x",
    )


def _balance_verification(
    status: VerificationStatus,
) -> BalanceVerification:
    """Build a minimal BalanceVerification with the given status."""
    return BalanceVerification(
        status=status,
        opening_balance=None,
        closing_balance=None,
        total_credits=Decimal("0"),
        total_debits=Decimal("0"),
        expected_delta=None,
        actual_delta=Decimal("0"),
        discrepancy=None,
        message=status.value,
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


def test_missing_currency_balance_returns_unverifiable() -> None:
    txs = [_tx("100.00", "GBP"), _tx("50.00", "USD")]
    results = verify_balance_multi_currency(
        txs,
        balances={"GBP": (Decimal("0"), Decimal("100"))},
    )
    assert results["GBP"].status is VerificationStatus.VERIFIED
    assert results["USD"].status is VerificationStatus.UNVERIFIABLE


def test_none_currency_grouped_as_unknown() -> None:
    tx = Transaction(amount=Decimal("10.00"), description="x")
    results = verify_balance_multi_currency([tx])
    assert "UNKNOWN" in results
    assert results["UNKNOWN"].status is VerificationStatus.UNVERIFIABLE


def test_no_balances_returns_unverifiable_for_all() -> None:
    txs = [_tx("100.00", "GBP"), _tx("50.00", "EUR")]
    results = verify_balance_multi_currency(txs)
    assert results["GBP"].status is VerificationStatus.UNVERIFIABLE
    assert results["EUR"].status is VerificationStatus.UNVERIFIABLE


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


# ---------------------------------------------------------------------------
# aggregate_verifications
# ---------------------------------------------------------------------------


def test_aggregate_all_verified_is_verified() -> None:
    txs = [
        _tx("100.00", "GBP"),
        _tx("200.00", "EUR"),
    ]
    results = verify_balance_multi_currency(
        txs,
        balances={
            "GBP": (Decimal("0"), Decimal("100")),
            "EUR": (Decimal("0"), Decimal("200")),
        },
    )
    aggregate = aggregate_verifications(results)
    assert aggregate.status is VerificationStatus.VERIFIED
    assert aggregate.total_credits == Decimal("300.00")
    assert aggregate.total_debits == Decimal("0")
    assert aggregate.opening_balance is None
    assert aggregate.expected_delta is None
    assert "Multi-currency statement" in aggregate.message
    assert "EUR" in aggregate.message
    assert "GBP" in aggregate.message


def test_aggregate_discrepancy_wins_over_unverifiable() -> None:
    txs = [
        _tx("100.00", "GBP"),
        _tx("200.00", "EUR"),
    ]
    results = verify_balance_multi_currency(
        txs,
        balances={"GBP": (Decimal("0"), Decimal("999"))},  # EUR missing
    )
    aggregate = aggregate_verifications(results)
    assert aggregate.status is VerificationStatus.DISCREPANCY


def test_aggregate_unverifiable_when_any_currency_unverifiable() -> None:
    txs = [
        _tx("100.00", "GBP"),
        _tx("200.00", "EUR"),
    ]
    results = verify_balance_multi_currency(
        txs,
        balances={"GBP": (Decimal("0"), Decimal("100"))},  # EUR missing
    )
    aggregate = aggregate_verifications(results)
    assert aggregate.status is VerificationStatus.UNVERIFIABLE


def test_aggregate_failed_takes_precedence_over_unverifiable() -> None:
    """FAILED (genuine error) outranks UNVERIFIABLE but not DISCREPANCY."""
    verified = _balance_verification(VerificationStatus.VERIFIED)
    unverifiable = _balance_verification(VerificationStatus.UNVERIFIABLE)
    failed = _balance_verification(VerificationStatus.FAILED)
    aggregate = aggregate_verifications(
        {
            "GBP": verified,
            "EUR": unverifiable,
            "USD": failed,
        }
    )
    assert aggregate.status is VerificationStatus.FAILED


def test_aggregate_empty_results_raises() -> None:
    with pytest.raises(ValueError, match="requires results"):
        aggregate_verifications({})


# ---------------------------------------------------------------------------
# verify_transactions (currency-aware dispatch)
# ---------------------------------------------------------------------------


def test_verify_transactions_single_currency_uses_golden_rule() -> None:
    txs = [_tx("100.00", "GBP"), _tx("-30.00", "GBP")]
    result = verify_transactions(
        txs,
        opening_balance=Decimal("500"),
        closing_balance=Decimal("570"),
    )
    assert result.status is VerificationStatus.VERIFIED
    assert result.opening_balance == Decimal("500")


def test_verify_transactions_no_currency_metadata_uses_golden_rule() -> None:
    txs = [
        Transaction(amount=Decimal("100.00"), description="x"),
        Transaction(amount=Decimal("-30.00"), description="y"),
    ]
    result = verify_transactions(
        txs,
        opening_balance=Decimal("0"),
        closing_balance=Decimal("70"),
    )
    assert result.status is VerificationStatus.VERIFIED


def test_verify_transactions_multi_currency_avoids_false_discrepancy() -> None:
    """Mixed currencies must not be summed into one Golden Rule check."""
    txs = [
        _tx("100.00", "GBP"),
        _tx("200.00", "EUR"),
    ]
    # Balances cannot be attributed to one currency: the statement
    # reports UNVERIFIABLE (cannot verify) instead of a spurious
    # mismatch.
    result = verify_transactions(
        txs,
        opening_balance=Decimal("0"),
        closing_balance=Decimal("100"),
    )
    assert result.status is VerificationStatus.UNVERIFIABLE
    assert "Multi-currency statement" in result.message


def test_verify_transactions_missing_balances_unverifiable() -> None:
    txs = [_tx("100.00", "GBP")]
    result = verify_transactions(
        txs,
        opening_balance=None,
        closing_balance=None,
    )
    assert result.status is VerificationStatus.UNVERIFIABLE
