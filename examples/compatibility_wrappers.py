"""
Example: legacy compatibility wrappers from bank_statement_parsers.py.
"""
# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser.bank_statement_parsers import (
    Camt053Parser,
    Pain001Parser,
)
from common import CAMT_FIXTURE, PAIN001_FIXTURE


def main() -> None:
    """Demonstrate the backward-compatible parser class wrappers."""
    camt = Camt053Parser(str(CAMT_FIXTURE), redact_pii=True)
    pain = Pain001Parser(str(PAIN001_FIXTURE), redact_pii=True)

    print(
        f"Camt053Parser: {len(camt.statements)} statements, "
        f"{len(camt.transactions)} transactions"
    )
    print(
        f"Pain001Parser wrapper: {pain.batches_count} batches, "
        f"{pain.total_payments_count} payments"
    )


if __name__ == "__main__":
    main()
