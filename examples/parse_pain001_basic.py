"""
Example: basic PAIN.001 parsing.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import Pain001Parser  # noqa: E402
from common import PAIN001_FIXTURE  # noqa: E402


def main() -> None:
    parser = Pain001Parser(str(PAIN001_FIXTURE))
    payments = parser.parse()

    print(f"Input: {PAIN001_FIXTURE}")
    print(f"Payments parsed: {len(payments)}")
    print(payments.head().to_string(index=False))
    print(parser.get_summary())


if __name__ == "__main__":
    main()
