"""
Example: auto-detect a supported statement format and parse it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Detect statement formats and parse each sample accordingly."""
    from bankstatementparser import (
        create_parser,
        detect_statement_format,
    )

    samples = [
        ROOT / "tests" / "test_data" / "sample_statement.csv",
        ROOT / "tests" / "test_data" / "sample.ofx",
        ROOT / "tests" / "test_data" / "sample.mt940",
        ROOT / "tests" / "test_data" / "camt.053.001.02.xml",
    ]

    for sample in samples:
        format_name = detect_statement_format(sample)
        parser = create_parser(sample, format_name)
        frame = parser.parse()
        print(f"{sample.name}: {format_name} -> {len(frame)} rows")


if __name__ == "__main__":
    main()
