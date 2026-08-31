# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Tests for hash-set based idempotent deduplication."""

from __future__ import annotations

from decimal import Decimal

from bankstatementparser import Deduplicator, Transaction
from bankstatementparser.transaction_models import normalize_description


def _tx(amount: str, desc: str, day: str = "2026-04-01") -> Transaction:
    return Transaction(
        amount=Decimal(amount),
        booking_date=day,  # type: ignore[arg-type]
        description=desc,
        normalized_description=normalize_description(desc),
    )


def test_dedupe_by_hash_keeps_genuine_within_batch_repeats() -> None:
    # Two identical same-day purchases in one statement are real
    # transactions, not duplicates — occurrence counting keeps both.
    dedup = Deduplicator()
    txs = [
        _tx("10.00", "Coffee"),
        _tx("10.00", "Coffee"),
        _tx("20.00", "Lunch"),
    ]
    unique, skipped = dedup.dedupe_by_hash(txs)
    assert len(unique) == 3
    assert skipped == []


def test_dedupe_by_hash_reingestion_is_idempotent() -> None:
    dedup = Deduplicator()
    seen: set[str] = set()
    txs = [
        _tx("10.00", "Coffee"),
        _tx("10.00", "Coffee"),
        _tx("20.00", "Lunch"),
    ]
    unique, _skipped = dedup.dedupe_by_hash(txs, seen_hashes=seen)
    assert len(unique) == 3

    unique2, skipped2 = dedup.dedupe_by_hash(txs, seen_hashes=seen)
    assert unique2 == []
    assert len(skipped2) == 3
    assert skipped2[0] == txs[0].transaction_hash


def test_dedupe_by_hash_respects_seen_state() -> None:
    dedup = Deduplicator()
    seen: set[str] = set()
    first_batch = [_tx("10.00", "Coffee")]
    unique, _ = dedup.dedupe_by_hash(first_batch, seen_hashes=seen)
    assert len(unique) == 1
    assert seen  # state mutated in-place

    second_batch = [_tx("10.00", "Coffee"), _tx("5.00", "Tea")]
    unique2, skipped2 = dedup.dedupe_by_hash(second_batch, seen_hashes=seen)
    assert len(unique2) == 1
    assert len(skipped2) == 1


def test_transaction_hash_is_stable_across_sources() -> None:
    a = _tx("10.00", "Coffee")
    b = _tx("10.00", "  COFFEE  ")
    # Normalized descriptions match -> same hash
    assert a.transaction_hash == b.transaction_hash


def test_normalize_strips_inline_dates_and_ids() -> None:
    a = normalize_description("AMZN MKTPLACE 2026-04-01 #A1B2C3")
    b = normalize_description("AMZN MKTPLACE 2026-04-02 #Z9Y8X7")
    assert a == b
    assert "amzn" in a
    assert "mktplace" in a
    assert "2026" not in a


def test_normalize_strips_times_and_short_dates() -> None:
    assert normalize_description(
        "CARD PAYMENT 12:49 COFFEE SHOP 01/04"
    ) == normalize_description("CARD PAYMENT 14:01 COFFEE SHOP 03/04")


def test_normalize_handles_none() -> None:
    assert normalize_description(None) == ""


def test_dedupe_by_hash_catches_amazon_repeats_across_batches() -> None:
    # The same purchase re-exported with a different junk reference ID
    # in its description is caught on re-ingestion: normalization
    # strips the ID, so the hashes match across batches.
    dedup = Deduplicator()
    seen: set[str] = set()
    first = Transaction(
        amount=Decimal("9.99"),
        booking_date="2026-04-01",  # type: ignore[arg-type]
        description="AMZN MKTPLACE 2026-04-01 #A1B2C3",
        normalized_description=normalize_description(
            "AMZN MKTPLACE 2026-04-01 #A1B2C3"
        ),
    )
    second = Transaction(
        amount=Decimal("9.99"),
        booking_date="2026-04-01",  # type: ignore[arg-type]
        description="AMZN MKTPLACE 2026-04-01 #Z9Y8X7",
        normalized_description=normalize_description(
            "AMZN MKTPLACE 2026-04-01 #Z9Y8X7"
        ),
    )
    unique, _ = dedup.dedupe_by_hash([first], seen_hashes=seen)
    assert len(unique) == 1

    unique2, skipped2 = dedup.dedupe_by_hash([second], seen_hashes=seen)
    assert unique2 == []
    assert len(skipped2) == 1


def test_transaction_hash_disambiguates_by_transaction_id() -> None:
    # Distinct same-day, same-amount transactions with different
    # bank-assigned IDs must not collide.
    a = Transaction(
        amount=Decimal("10.00"),
        booking_date="2026-04-01",  # type: ignore[arg-type]
        description="Coffee",
        normalized_description=normalize_description("Coffee"),
        transaction_id="FITID-1",
    )
    b = Transaction(
        amount=Decimal("10.00"),
        booking_date="2026-04-01",  # type: ignore[arg-type]
        description="Coffee",
        normalized_description=normalize_description("Coffee"),
        transaction_id="FITID-2",
    )
    assert a.transaction_hash != b.transaction_hash
