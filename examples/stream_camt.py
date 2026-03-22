"""
Example: stream CAMT transactions incrementally.
"""

from __future__ import annotations

import sys
from itertools import islice
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import CamtParser  # noqa: E402
from common import CAMT_FIXTURE  # noqa: E402


def main() -> None:
    parser = CamtParser(str(CAMT_FIXTURE))

    for index, transaction in enumerate(
        islice(parser.parse_streaming(redact_pii=True), 5), start=1
    ):
        print(f"Transaction {index}")
        print(transaction)


if __name__ == "__main__":
    main()
