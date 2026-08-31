#!/usr/bin/env python3
"""Verify Poetry lock entries carry SHA-256 hashes for every distribution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def load_lockfile() -> dict[str, Any]:
    """Parse the repository's poetry.lock file into a dictionary."""
    with (ROOT / "poetry.lock").open("rb") as handle:
        return cast(dict[str, Any], tomllib.load(handle))


def verify_packages(packages: list[dict[str, Any]]) -> list[str]:
    """Return failure messages for packages lacking SHA-256 file hashes."""
    failures = []
    for package in packages:
        package_id = f"{package['name']}=={package['version']}"
        files = package.get("files", [])
        if not files:
            failures.append(f"{package_id}: missing files entries")
            continue
        for file_entry in files:
            digest = file_entry.get("hash", "")
            if not digest.startswith("sha256:"):
                failures.append(
                    f"{package_id}: invalid hash for {file_entry.get('file', '<unknown>')}"
                )
    return failures


def main() -> int:
    """Verify locked package hashes and exit non-zero on any failure."""
    packages = load_lockfile().get("package", [])
    failures = verify_packages(packages)
    if failures:
        print("Poetry lock hash verification failed:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print(f"Verified SHA-256 hashes for {len(packages)} locked packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
