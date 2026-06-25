#!/usr/bin/env python3
"""Generate deterministic SHA-256 checksums for build artifacts."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Iterable
from pathlib import Path


def iter_files(directory: Path) -> Iterable[Path]:
    """Yield the regular files in a directory in sorted order."""
    for path in sorted(directory.iterdir()):
        if path.is_file():
            yield path


def file_checksum(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the checksum generator."""
    parser = argparse.ArgumentParser(
        description="Generate SHA-256 checksums for all files in a directory."
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing artifacts to checksum.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file. Defaults to <directory>/SHA256SUMS.",
    )
    return parser.parse_args()


def main() -> int:
    """Write SHA-256 checksums for a directory's files to an output file."""
    args = parse_args()
    output_path = args.output or (args.directory / "SHA256SUMS")
    output_lines = []
    for file_path in iter_files(args.directory):
        if file_path == output_path:
            continue
        output_lines.append(f"{file_checksum(file_path)}  {file_path.name}")
    output_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(output_lines)} checksums to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
