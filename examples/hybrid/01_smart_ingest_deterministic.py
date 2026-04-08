"""
Example 01 — Path A: deterministic extraction.

Demonstrates that `smart_ingest()` routes a CAMT.053 (ISO 20022) file
straight through the deterministic parser when the format is
detected. No PDF, no LLM, no API key — this path costs $0.00 and is
100% reproducible byte-for-byte.

This is the "best of both worlds" idea in action: pay for nothing
when the source is already structured.

Run from the repository root:

    python examples/hybrid/01_smart_ingest_deterministic.py

Cross-platform:
  macOS / Linux / WSL — works identically. No optional extras
  required for this script — only the core install.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser.hybrid import smart_ingest  # noqa: E402

CAMT_FIXTURE = REPO_ROOT / "tests" / "test_data" / "camt.053.001.02.xml"


def main() -> int:
    if not CAMT_FIXTURE.exists():
        print(f"Fixture not found: {CAMT_FIXTURE}", file=sys.stderr)
        return 1

    print(f"Input: {CAMT_FIXTURE.relative_to(REPO_ROOT)}")
    print()
    print("Calling smart_ingest()...")
    print()

    result = smart_ingest(CAMT_FIXTURE)

    print(f"  Source method:    {result.source_method}")
    print(f"  Source format:    {result.source_format}")
    print(f"  Transactions:     {len(result.transactions)}")
    print(f"  Verification:     {result.verification}")
    print(f"  Warnings:         {result.warnings or '(none)'}")
    print()

    if result.transactions:
        print("First 5 transactions (audit-friendly fields only):")
        print()
        print(f"  {'idx':>3}  {'date':<10}  {'amount':>12}  {'hash[:8]':<10}  description")
        print(f"  {'---':>3}  {'-' * 10}  {'-' * 12}  {'-' * 10}  {'-' * 40}")
        for idx, tx in enumerate(result.transactions[:5]):
            booking = tx.booking_date.isoformat() if tx.booking_date else ""
            print(
                f"  {idx:>3}  {booking:<10}  "
                f"{str(tx.amount):>12}  "
                f"{tx.transaction_hash[:8]:<10}  "
                f"{(tx.description or '')[:40]}"
            )
        print()

    print("Notice that every transaction carries:")
    print(f"  - source_method='{result.transactions[0].source_method}' (audit trail)")
    print("  - transaction_hash (idempotent fingerprint, MD5 of date|desc|amount)")
    print(f"  - confidence={result.transactions[0].confidence} (None for deterministic rows)")
    print()
    print("Path A complete. Cost: $0.00. Network calls: 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
