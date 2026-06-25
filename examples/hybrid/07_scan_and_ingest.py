"""
Example 07 — Bulk directory ingest with `scan_and_ingest()`.

`smart_ingest()` handles one file; `scan_and_ingest()` walks a whole
directory, runs `smart_ingest()` on every match, deduplicates
transactions across files by `transaction_hash`, and (when two or more
statements are ingested) runs a cross-statement continuity check so a
missing month or a duplicated export surfaces immediately.

This is the batch-treasury workflow: point it at a folder of monthly
statements and get back one clean, de-duplicated transaction set plus
an integrity verdict.

Run from the repository root:

    python examples/hybrid/07_scan_and_ingest.py

Cross-platform: pure Python, no optional extras required — this script
copies the bundled CAMT fixture into a temporary directory so it is
fully self-contained and deterministic.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser.hybrid import scan_and_ingest  # noqa: E402

CAMT_FIXTURE = REPO_ROOT / "tests" / "test_data" / "camt.053.001.02.xml"


def main() -> int:
    """Run scan_and_ingest over a temporary folder of statements."""
    if not CAMT_FIXTURE.exists():
        print(f"Fixture not found: {CAMT_FIXTURE}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as raw_dir:
        directory = Path(raw_dir)
        # Two copies of the same statement: a realistic "I exported the
        # same month twice" mistake. The cross-file hash dedup collapses
        # the duplicate rows back into a single clean set.
        shutil.copy(CAMT_FIXTURE, directory / "january.xml")
        shutil.copy(CAMT_FIXTURE, directory / "january-again.xml")

        print(f"Scanning: {directory}")
        print()
        print("Calling scan_and_ingest()...")
        print()

        result = scan_and_ingest(directory, extensions={".xml"})

        print(f"  Files ingested:        {result.file_count}")
        print(f"  Unique transactions:   {result.total_unique}")
        print(f"  Duplicate rows skipped: {result.total_skipped}")
        print(f"  Failures:              {result.failure_count}")
        if result.continuity is not None:
            print(
                f"  Continuity status:     "
                f"{result.continuity.status.value.upper()}"
            )
        print()

    print(
        "scan_and_ingest() deduplicated the re-exported month by "
        "transaction_hash,"
    )
    print("so each booking appears exactly once in unique_transactions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
