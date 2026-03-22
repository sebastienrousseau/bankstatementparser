"""
Example: parse CAMT.053 XML files directly from a ZIP archive.

This example uses the ISO 20022 CAMT.053 format, which is a real bank
statement format commonly exported by European and international banks.

Usage:
    python examples/parse_camt_zip.py path/to/statements.zip

To build a demo ZIP from the repository's real-format fixture:
    python examples/parse_camt_zip.py --build-demo-zip /tmp/camt-demo.zip
    python examples/parse_camt_zip.py /tmp/camt-demo.zip
"""
# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import CamtParser, iter_secure_xml_entries
from common import CAMT_FIXTURE


def build_demo_zip(output_zip: Path) -> None:
    """
    Create a demo ZIP using the repository's CAMT.053 fixture.

    The fixture is a real ISO 20022 CAMT.053 XML structure and is suitable
    for demonstrating multi-entry ZIP processing without inventing a custom
    format.
    """
    fixture_bytes = CAMT_FIXTURE.read_bytes()

    with ZipFile(output_zip, "w") as zf:
        zf.writestr("bank-export/statement-001.xml", fixture_bytes)
        zf.writestr("bank-export/statement-002.xml", fixture_bytes)


def parse_zip(zip_path: Path) -> None:
    """
    Parse XML entries from a ZIP archive without extracting them to disk.

    This example uses the repository's hardened ZIP validation helper before
    parsing any XML member.
    """
    max_entry_size = 10 * 1024 * 1024  # 10MB per XML member

    for xml_source in iter_secure_xml_entries(
        zip_path,
        max_entry_size=max_entry_size,
        max_total_uncompressed_size=20 * 1024 * 1024,
        max_compression_ratio=100.0,
    ):
        parser = CamtParser.from_bytes(
            xml_source.xml_bytes,
            source_name=xml_source.source_name,
            max_bytes=max_entry_size,
        )
        transactions = parser.parse()

        print(
            f"{xml_source.source_name}: {len(transactions)} transactions parsed"
        )


def main() -> None:
    """CLI entry point for the ZIP example."""
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", nargs="?")
    parser.add_argument("--build-demo-zip", dest="build_demo_zip")
    args = parser.parse_args()

    if args.build_demo_zip:
        output_zip = Path(args.build_demo_zip).resolve()
        build_demo_zip(output_zip)
        print(f"Demo ZIP created at {output_zip}")
        return

    if not args.zip_path:
        raise SystemExit(
            "Provide a ZIP file path or use --build-demo-zip to create one."
        )

    parse_zip(Path(args.zip_path).resolve())


if __name__ == "__main__":
    main()
