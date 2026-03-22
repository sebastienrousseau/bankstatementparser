"""
Example: export parsed CAMT data to CSV and JSON.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import CamtParser  # noqa: E402
from common import CAMT_FIXTURE  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", default="example-output/camt"
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    camt = CamtParser(str(CAMT_FIXTURE))
    csv_path = output_dir / "camt-transactions.csv"
    json_path = output_dir / "camt-transactions.json"

    camt.export_csv(csv_path)
    camt.export_json(json_path)

    print(f"CSV exported to {csv_path}")
    print(f"JSON exported to {json_path}")


if __name__ == "__main__":
    main()
