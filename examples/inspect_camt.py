"""
Example: inspect CAMT balances, transactions, stats, and summary.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import CamtParser  # noqa: E402
from common import CAMT_FIXTURE  # noqa: E402


def main() -> None:
    """Inspect balances, transactions, and summary stats of a CAMT file."""
    parser = CamtParser(str(CAMT_FIXTURE))

    balances = parser.get_account_balances()
    transactions = parser.get_transactions(redact_pii=True)
    stats = parser.get_statement_stats()
    summary = parser.get_summary()

    print("Balances")
    print(balances.to_string(index=False))
    print("\nTransactions (PII-redacted addresses)")
    print(transactions.head().to_string(index=False))
    print("\nStatement stats")
    print(stats.to_string(index=False))
    print("\nSummary")
    print(summary)


if __name__ == "__main__":
    main()
