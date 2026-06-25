"""
Example: stream PAIN.001 payments incrementally.
"""

from __future__ import annotations

import sys
from itertools import islice
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import Pain001Parser  # noqa: E402
from common import PAIN001_FIXTURE  # noqa: E402


def main() -> None:
    """Stream the first few payments from a pain.001 fixture."""
    parser = Pain001Parser(str(PAIN001_FIXTURE))

    for index, payment in enumerate(
        islice(parser.parse_streaming(redact_pii=True), 5), start=1
    ):
        print(f"Payment {index}")
        print(payment)


if __name__ == "__main__":
    main()
