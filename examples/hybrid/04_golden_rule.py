"""
Example 04 — The Golden Rule.

`opening_balance + credits - debits == closing_balance`

If that equation does not hold, the statement is "Unverified" and a
human needs to look at it. This example walks through every state
the verifier can return:

  VERIFIED       arithmetic checks out within tolerance
  DISCREPANCY    arithmetic disagrees beyond tolerance
  UNVERIFIABLE   the source did not provide both balances

Run from the repository root:

    python examples/hybrid/04_golden_rule.py

Cross-platform: pure Python, no extras required.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import Transaction  # noqa: E402
from bankstatementparser.hybrid import (  # noqa: E402
    VerificationStatus,
    verify_balance,
)


def _row(amount: str, day: str, desc: str) -> Transaction:
    return Transaction(
        amount=Decimal(amount),
        booking_date=day,  # type: ignore[arg-type]
        description=desc,
    )


# Same statement, three integrity scenarios.
HAPPY_PATH: list[Transaction] = [
    _row("2500.00", "2026-04-01", "Salary"),
    _row("-1200.00", "2026-04-01", "Rent"),
    _row("-89.50", "2026-04-04", "British Gas"),
    _row("-29.99", "2026-04-05", "Amazon"),
    _row("-3.85", "2026-04-08", "Coffee"),
]

# A row dropped in transcription — debits are 89.50 short.
DROPPED_ROW: list[Transaction] = [
    _row("2500.00", "2026-04-01", "Salary"),
    _row("-1200.00", "2026-04-01", "Rent"),
    # MISSING: British Gas 89.50
    _row("-29.99", "2026-04-05", "Amazon"),
    _row("-3.85", "2026-04-08", "Coffee"),
]


def _print(label: str, result: object) -> None:
    print(f"-- {label}")
    print(f"   status:         {result.status.value.upper()}")  # type: ignore[attr-defined]
    print(f"   total credits:  {result.total_credits}")  # type: ignore[attr-defined]
    print(f"   total debits:   {result.total_debits}")  # type: ignore[attr-defined]
    print(f"   expected delta: {result.expected_delta}")  # type: ignore[attr-defined]
    print(f"   actual delta:   {result.actual_delta}")  # type: ignore[attr-defined]
    print(f"   discrepancy:    {result.discrepancy}")  # type: ignore[attr-defined]
    print(f"   message:        {result.message}")  # type: ignore[attr-defined]
    print()


def _expect(actual: VerificationStatus, expected: VerificationStatus) -> None:
    if actual is not expected:
        raise SystemExit(
            f"Example contract violated: expected {expected.value}, "
            f"got {actual.value}"
        )


def main() -> int:
    print("Scenario 1: clean statement, all transactions captured")
    print()
    result = verify_balance(
        HAPPY_PATH,
        opening_balance=Decimal("1500.00"),
        closing_balance=Decimal("2676.66"),
    )
    _print("VERIFIED expected", result)
    _expect(result.status, VerificationStatus.VERIFIED)

    print("Scenario 2: one row dropped during extraction")
    print()
    result = verify_balance(
        DROPPED_ROW,
        opening_balance=Decimal("1500.00"),
        closing_balance=Decimal("2676.66"),
    )
    _print("DISCREPANCY expected", result)
    _expect(result.status, VerificationStatus.DISCREPANCY)
    print("  -> Action: flag statement 'Unverified', do not auto-import.")
    print(f"  -> Hint: missing debit of {abs(result.discrepancy or 0)}")
    print()

    print("Scenario 3: source provided no balances at all")
    print()
    result = verify_balance(
        HAPPY_PATH,
        opening_balance=None,
        closing_balance=None,
    )
    _print("UNVERIFIABLE expected", result)
    _expect(result.status, VerificationStatus.UNVERIFIABLE)
    print("  -> Action: ask the operator to supply balances manually,")
    print("     or skip integrity check entirely (LLMs sometimes miss them).")
    print()

    print("All three scenarios behave as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
