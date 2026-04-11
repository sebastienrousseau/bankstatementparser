# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for hledger and beancount export (#v0.0.8)."""

from __future__ import annotations

from decimal import Decimal

from bankstatementparser import Transaction
from bankstatementparser.export import to_beancount, to_hledger


def _tx(
    amount: str,
    desc: str,
    *,
    day: str = "2026-04-01",
    currency: str = "EUR",
    category: str | None = None,
    counterparty: str | None = None,
) -> Transaction:
    return Transaction(
        amount=Decimal(amount),
        booking_date=day,  # type: ignore[arg-type]
        description=desc,
        currency=currency,
        category=category,
        counterparty=counterparty,
    )


# ---------------------------------------------------------------------------
# hledger
# ---------------------------------------------------------------------------


def test_hledger_basic_output() -> None:
    txs = [_tx("-3.85", "Coffee Shop")]
    journal = to_hledger(txs)
    assert "2026-04-01 Coffee Shop" in journal
    assert "Assets:Bank:Checking    EUR -3.85" in journal
    assert "Expenses:Uncategorized" in journal


def test_hledger_uses_category_as_contra_account() -> None:
    txs = [_tx("-3.85", "Coffee", category="Food and Drink")]
    journal = to_hledger(txs)
    assert "Expenses:Food:and:Drink" in journal
    assert "Uncategorized" not in journal


def test_hledger_custom_account_and_currency() -> None:
    txs = [_tx("2500.00", "Salary", currency="GBP")]
    journal = to_hledger(
        txs,
        account="Assets:Bank:HSBC",
        default_currency="GBP",
    )
    assert "Assets:Bank:HSBC    GBP 2500" in journal


def test_hledger_missing_date_uses_epoch() -> None:
    tx = Transaction(amount=Decimal("10"), description="No date")
    journal = to_hledger([tx])
    assert "1970-01-01" in journal


def test_hledger_missing_description() -> None:
    tx = Transaction(amount=Decimal("10"))
    journal = to_hledger([tx])
    assert "Unknown" in journal


def test_hledger_multiple_transactions() -> None:
    txs = [
        _tx("-3.85", "Coffee"),
        _tx("2500.00", "Salary"),
    ]
    journal = to_hledger(txs)
    assert journal.count("Assets:Bank:Checking") == 2


# ---------------------------------------------------------------------------
# beancount
# ---------------------------------------------------------------------------


def test_beancount_basic_output() -> None:
    txs = [_tx("-3.85", "Coffee Shop", counterparty="Costa")]
    journal = to_beancount(txs)
    assert '2026-04-01 txn "Costa" "Coffee Shop"' in journal
    assert "Assets:Bank:Checking  -3.85 EUR" in journal
    assert "Expenses:Uncategorized  3.85 EUR" in journal


def test_beancount_uses_category_as_contra_account() -> None:
    txs = [_tx("-3.85", "Coffee", category="Food and Drink")]
    journal = to_beancount(txs)
    assert "Expenses:Food:and:Drink" in journal


def test_beancount_escapes_quotes_in_narration() -> None:
    txs = [_tx("-1.00", 'The "Best" Shop')]
    journal = to_beancount(txs)
    assert 'The \\"Best\\" Shop' in journal


def test_beancount_missing_counterparty() -> None:
    txs = [_tx("-1.00", "Coffee")]
    journal = to_beancount(txs)
    assert 'txn "" "Coffee"' in journal


def test_beancount_missing_date_uses_epoch() -> None:
    tx = Transaction(amount=Decimal("10"), description="No date")
    journal = to_beancount([tx])
    assert "1970-01-01" in journal


def test_beancount_custom_account_and_currency() -> None:
    txs = [_tx("100.00", "Salary", currency="GBP")]
    journal = to_beancount(
        txs,
        account="Assets:Bank:HSBC",
        default_currency="GBP",
    )
    assert "Assets:Bank:HSBC  100 GBP" in journal
