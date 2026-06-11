"""
Example 05 — Idempotent dedup of recurring charges.

The classic LLM-extraction failure mode for incremental ingestion:
the same merchant on different days produces *almost-identical*
descriptions that change by one character ("AMZN MKTPLACE 2026-04-01
#A1B2C3" vs "AMZN MKTPLACE 2026-04-02 #Z9Y8X7"). A naive
`hash(description)` would treat them as different rows; a strict
SHA of `(date, description, amount)` would also fail because the
date and reference rotate.

v0.0.5 fixes this in two layers:

  1. `normalize_description()` strips inline dates, times, and long
     alphanumeric IDs before lowercasing.

  2. `Transaction.transaction_hash` is MD5 of
     `(booking_date | normalized_description | amount)`. So two
     visits to the same merchant on the same date with rotating
     reference IDs produce the *same* hash.

  3. `Deduplicator.dedupe_by_hash()` is a strict identity filter
     designed for incremental ingestion (sync to a database, append
     to a Google Sheet, etc.). It mutates a caller-owned set so you
     can persist state between batches.

Run from the repository root:

    python examples/hybrid/05_dedupe_recurring.py

Cross-platform: pure Python, no extras required.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import Deduplicator, Transaction  # noqa: E402
from bankstatementparser.transaction_models import (  # noqa: E402
    normalize_description,
)


def _tx(amount: str, day: str, raw_desc: str) -> Transaction:
    return Transaction(
        amount=Decimal(amount),
        booking_date=day,  # type: ignore[arg-type]
        description=raw_desc,
        normalized_description=normalize_description(raw_desc),
    )


def main() -> int:
    print("=" * 64)
    print("PART 1 — normalize_description() strips noise")
    print("=" * 64)
    print()

    pairs = [
        (
            "AMZN MKTPLACE 2026-04-01 #A1B2C3",
            "AMZN MKTPLACE 2026-04-02 #Z9Y8X7",
        ),
        ("CARD PAYMENT 12:49 COFFEE SHOP", "CARD PAYMENT 14:01 COFFEE SHOP"),
        ("UBER EATS 03/04", "UBER EATS 05/04"),
    ]

    for left, right in pairs:
        n_left = normalize_description(left)
        n_right = normalize_description(right)
        match = "==" if n_left == n_right else "!="
        print(f"  raw:        {left}")
        print(f"  raw:        {right}")
        print(f"  normalized: {n_left}")
        print(f"  normalized: {n_right}")
        print(f"  result:     {match}")
        print()

    print("=" * 64)
    print("PART 2 — Transaction.transaction_hash is stable")
    print("=" * 64)
    print()

    a = _tx("-29.99", "2026-04-01", "AMZN MKTPLACE 2026-04-01 #A1B2C3")
    b = _tx("-29.99", "2026-04-01", "AMZN MKTPLACE 2026-04-01 #Z9Y8X7")
    print(f"  tx A hash: {a.transaction_hash}")
    print(f"  tx B hash: {b.transaction_hash}")
    print(f"  same?      {a.transaction_hash == b.transaction_hash}")
    print()

    print("=" * 64)
    print("PART 3 — dedupe_by_hash() across two ingestion batches")
    print("=" * 64)
    print()

    dedup = Deduplicator()
    seen: set[str] = set()

    print("Batch 1 (today's statement):")
    batch_1 = [
        _tx("-3.85", "2026-04-08", "CARD PAYMENT 08:15 COFFEE SHOP"),
        _tx("-29.99", "2026-04-08", "AMZN MKTPLACE 2026-04-08 #A1B2C3"),
        _tx("-7.40", "2026-04-08", "CONTACTLESS TFL TRAVEL"),
        # Operator accidentally included the same row twice in the
        # upload — the LLM produced two slightly different references.
        _tx("-29.99", "2026-04-08", "AMZN MKTPLACE 2026-04-08 #Z9Y8X7"),
    ]
    unique, skipped = dedup.dedupe_by_hash(batch_1, seen_hashes=seen)
    print(f"  in:      {len(batch_1)}")
    print(f"  unique:  {len(unique)}  (the duplicate Amazon row was caught)")
    print(f"  skipped: {len(skipped)}  -> {skipped}")
    print()

    print("Batch 2 (re-upload of the same statement):")
    batch_2 = [
        _tx("-3.85", "2026-04-08", "CARD PAYMENT 08:15 COFFEE SHOP"),
        _tx("-29.99", "2026-04-08", "AMZN MKTPLACE 2026-04-08 #Q1Q2Q3"),
        _tx("-12.50", "2026-04-09", "DELIVEROO 14:22"),  # truly new row
    ]
    unique, skipped = dedup.dedupe_by_hash(batch_2, seen_hashes=seen)
    print(f"  in:      {len(batch_2)}")
    print(f"  unique:  {len(unique)}  (only the Deliveroo row is new)")
    print(f"  skipped: {len(skipped)}  -> already-seen hashes")
    print()

    print(f"State after both batches: {len(seen)} distinct hashes tracked")
    print()
    print("Use case: pass `seen_hashes=set(my_db.fetch_all_hashes())`")
    print("at the start of each ingestion job to make the whole pipeline")
    print("idempotent — re-running it never double-imports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
