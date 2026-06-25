"""
Example: export CAMT.053 transactions to an Excel workbook.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import CamtParser  # noqa: E402
from common import CAMT_FIXTURE  # noqa: E402


def main() -> None:
    """Export a CAMT fixture to an Excel workbook."""
    parser = CamtParser(str(CAMT_FIXTURE))
    output = Path(tempfile.gettempdir()) / "camt_export.xlsx"
    parser.camt_to_excel(str(output))
    print(f"Excel workbook written to {output}")


if __name__ == "__main__":
    main()
