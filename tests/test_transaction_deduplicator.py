"""Tests for deterministic transaction normalization and deduplication."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from bankstatementparser import Deduplicator, Transaction
from bankstatementparser.transaction_deduplicator import (
    _description_similarity,
)
from bankstatementparser.transaction_models import (
    _coerce_decimal,
    _parse_date,
    normalize_description,
)


def test_transaction_from_camt_style_record() -> None:
    transaction = Transaction.from_record(
        {
            "AccountId": "GB12BANK123456789",
            "Currency": "eur",
            "Amount": "-12.30",
            "BookgDt": "2026-03-20",
            "ValDt": "2026-03-19",
            "Reference": "CARD PAYMENT 12:49 COFFEE SHOP",
            "Creditor": "Coffee Shop",
        },
        source="camt",
        source_index=2,
    )

    assert transaction.account_id == "GB12BANK123456789"
    assert transaction.currency == "EUR"
    assert transaction.amount == Decimal("-12.30")
    assert transaction.booking_date is not None
    assert transaction.value_date is not None
    assert transaction.description == "CARD PAYMENT 12:49 COFFEE SHOP"
    assert "card payment" in transaction.normalized_description
    assert transaction.counterparty == "Coffee Shop"
    assert transaction.source == "camt"
    assert transaction.source_index == 2


def test_transaction_from_csv_style_record() -> None:
    transaction = Transaction.from_record(
        {
            "account_id": "NL12BANK987654321",
            "currency": "usd",
            "amount": 250.0,
            "date": "20260321",
            "description": "Vendor payout batch 3311",
            "transaction_id": "abc123",
        }
    )

    assert transaction.account_id == "NL12BANK987654321"
    assert transaction.currency == "USD"
    assert transaction.amount == Decimal("250.0")
    assert transaction.booking_date is not None
    assert transaction.transaction_id == "abc123"


def test_deduplicator_finds_exact_duplicate_primary_hash_collision() -> None:
    deduplicator = Deduplicator()
    result = deduplicator.deduplicate(
        [
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "12.30",
                "date": "2026-03-20",
                "description": "Coffee shop",
            },
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "12.30",
                "date": "2026-03-20",
                "description": "Coffee shop",
            },
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "99.00",
                "date": "2026-03-20",
                "description": "Payroll",
            },
        ]
    )

    assert len(result.exact_duplicates) == 1
    assert len(result.exact_duplicates[0].transactions) == 2
    assert len(result.unique_transactions) == 1
    assert result.unique_transactions[0].description == "Payroll"


def test_deduplicator_marks_probable_match_for_fuzzy_description() -> None:
    deduplicator = Deduplicator(description_similarity_threshold=0.9)
    result = deduplicator.deduplicate(
        [
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "12.30",
                "date": "2026-03-20",
                "description": "Coffee Shop London",
            },
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "12.30",
                "date": "2026-03-20",
                "description": "Coffee Shop Londn",
            },
        ]
    )

    assert len(result.exact_duplicates) == 1
    assert len(result.suspected_matches) == 1
    assert result.suspected_matches[0].tier == "probable"
    assert "Primary hash collision" in result.suspected_matches[0].reason
    assert result.suspected_matches[0].confidence >= 0.9


def test_deduplicator_marks_suspected_date_shift_matches() -> None:
    deduplicator = Deduplicator(value_date_window_days=3)
    result = deduplicator.deduplicate(
        [
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "1200.00",
                "booking_date": "2026-03-20",
                "value_date": "2026-03-20",
                "description": "Salary March 2026",
            },
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "1200.00",
                "booking_date": "2026-03-24",
                "value_date": "2026-03-22",
                "description": "Salary March 2026",
            },
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "17.50",
                "booking_date": "2026-03-24",
                "value_date": "2026-03-24",
                "description": "Lunch",
            },
        ]
    )

    assert not result.exact_duplicates
    assert len(result.suspected_matches) == 1
    assert result.suspected_matches[0].tier == "suspected"
    assert "Value date shift" in result.suspected_matches[0].reason
    assert len(result.unique_transactions) == 1
    assert result.unique_transactions[0].description == "Lunch"


def test_deduplicator_excludes_suspected_with_custom_source_index() -> None:
    # source_index values from the caller (e.g. row offsets in a
    # larger file) must not leak into the exclusion logic, which
    # operates on enumeration indices.
    deduplicator = Deduplicator(value_date_window_days=3)
    base = {
        "account_id": "acct-1",
        "currency": "EUR",
        "amount": "1200.00",
        "description": "Salary March 2026",
    }
    txs = [
        Transaction.from_record(
            {
                **base,
                "booking_date": "2026-03-20",
                "value_date": "2026-03-20",
            },
            source_index=100,
        ),
        Transaction.from_record(
            {
                **base,
                "booking_date": "2026-03-24",
                "value_date": "2026-03-22",
            },
            source_index=200,
        ),
        Transaction.from_record(
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "17.50",
                "booking_date": "2026-03-24",
                "value_date": "2026-03-24",
                "description": "Lunch",
            },
            source_index=300,
        ),
    ]

    result = deduplicator.deduplicate(txs)

    assert len(result.suspected_matches) == 1
    assert len(result.unique_transactions) == 1
    assert result.unique_transactions[0].description == "Lunch"


def test_deduplicator_normalizes_from_dataframe() -> None:
    deduplicator = Deduplicator()
    df = pd.DataFrame(
        [
            {
                "AccountId": "acct-1",
                "Currency": "EUR",
                "Amount": 5.5,
                "BookgDt": "2026-03-20",
                "ValDt": "2026-03-20",
                "Reference": "Bus ticket",
            }
        ]
    )

    transactions = deduplicator.from_dataframe(df, source="camt")

    assert len(transactions) == 1
    assert transactions[0].source == "camt"
    assert transactions[0].amount == Decimal("5.5")


def test_transaction_model_helpers_cover_edge_cases() -> None:
    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("   ") is None
    assert _parse_date("2026-03-21").isoformat() == "2026-03-21"
    assert _parse_date("20260321").isoformat() == "2026-03-21"
    assert _parse_date("21/03/2026").isoformat() == "2026-03-21"
    assert _parse_date("2026/03/21").isoformat() == "2026-03-21"
    assert (
        _parse_date(pd.Timestamp("2026-03-21").date()).isoformat()
        == "2026-03-21"
    )
    with pytest.raises(ValueError, match="unsupported date format"):
        _parse_date("not-a-date")

    assert _coerce_decimal("2.50") == Decimal("2.50")
    with pytest.raises(ValueError, match="amount is required"):
        _coerce_decimal("")

    assert normalize_description(None) == ""


def test_description_similarity_returns_zero_without_normalized_text() -> None:
    left = Transaction.from_record(
        {
            "account_id": "acct-1",
            "currency": "EUR",
            "amount": "10.00",
            "date": "2026-03-20",
        }
    )
    right = Transaction.from_record(
        {
            "account_id": "acct-1",
            "currency": "EUR",
            "amount": "10.00",
            "date": "2026-03-20",
        }
    )

    assert _description_similarity(left, right) == 0.0


def test_deduplicator_normalizes_existing_transaction_instances() -> None:
    deduplicator = Deduplicator()
    transaction = Transaction.from_record(
        {
            "account_id": "acct-1",
            "currency": "EUR",
            "amount": "15.00",
            "date": "2026-03-20",
            "description": "Subscription",
        }
    )

    normalized = deduplicator.normalize_transactions(
        [transaction], source="csv"
    )

    assert normalized[0].source == "csv"
    assert normalized[0].source_index == 0


def test_deduplicator_temporal_matching_resets_components_cleanly() -> None:
    deduplicator = Deduplicator(value_date_window_days=3)
    result = deduplicator.deduplicate(
        [
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "55.00",
                "booking_date": "2026-03-20",
                "value_date": "2026-03-20",
                "description": "Utility payment",
            },
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "55.00",
                "booking_date": "2026-03-25",
                "value_date": "2026-03-22",
                "description": "Utility payment",
            },
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "55.00",
                "booking_date": "2026-04-10",
                "value_date": "2026-04-10",
                "description": None,
            },
        ]
    )

    assert len(result.suspected_matches) == 1
    assert result.suspected_matches[0].tier == "suspected"
    assert "description similarity" in result.suspected_matches[0].reason
    assert len(result.unique_transactions) == 1


def test_deduplicator_temporal_matching_without_similarity_reason() -> None:
    deduplicator = Deduplicator(value_date_window_days=3)
    result = deduplicator.deduplicate(
        [
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "77.00",
                "booking_date": "2026-03-20",
                "value_date": "2026-03-20",
            },
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "77.00",
                "booking_date": "2026-03-24",
                "value_date": "2026-03-22",
            },
        ]
    )

    assert len(result.suspected_matches) == 1
    assert result.suspected_matches[0].tier == "suspected"
    assert "description similarity" not in result.suspected_matches[0].reason


def test_deduplicator_leaves_unmatched_candidates_with_missing_value_dates() -> (
    None
):
    deduplicator = Deduplicator(value_date_window_days=3)
    result = deduplicator.deduplicate(
        [
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "88.00",
                "booking_date": "2026-03-20",
                "value_date": None,
                "description": "Manual correction",
            },
            {
                "account_id": "acct-1",
                "currency": "EUR",
                "amount": "88.00",
                "booking_date": "2026-03-24",
                "value_date": "2026-03-24",
                "description": "Manual correction",
            },
        ]
    )

    assert not result.exact_duplicates
    assert not result.suspected_matches
    assert len(result.unique_transactions) == 2
