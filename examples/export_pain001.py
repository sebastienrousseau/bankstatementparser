"""
Example: export parsed PAIN.001 data to CSV and JSON.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import Pain001Parser  # noqa: E402
from common import PAIN001_FIXTURE  # noqa: E402


def main() -> None:
    """Export a pain.001 fixture to the supported output formats."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="example-output/pain001")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pain = Pain001Parser(str(PAIN001_FIXTURE))
    csv_path = output_dir / "pain001-payments.csv"
    json_path = output_dir / "pain001-payments.json"

    pain.export_csv(csv_path)
    pain.export_json(json_path)

    print(f"CSV exported to {csv_path}")
    print(f"JSON exported to {json_path}")


if __name__ == "__main__":
    main()
