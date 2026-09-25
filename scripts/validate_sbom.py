#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Validate CycloneDX 1.5 JSON against pinned upstream schemas, offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas" / "cyclonedx" / "1.5"


def schema_validator(directory: Path = SCHEMAS) -> Draft7Validator:
    """Verify vendored file hashes and build a registry with no network retrieval."""
    schemas = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        expected, filename = line.split()
        path = directory / filename
        if (
            path.parent != directory
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(
                f"Vendored schema integrity check failed: {filename}"
            )
        if filename.endswith(".json"):
            schemas[filename] = json.loads(path.read_text())
    registry: Registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema))
        for schema in schemas.values()
    )
    schema = schemas["bom-1.5.schema.json"]
    Draft7Validator.check_schema(schema)
    return Draft7Validator(
        schema,
        registry=registry,
        format_checker=Draft7Validator.FORMAT_CHECKER,
    )


def validate_sbom(document: Any, directory: Path = SCHEMAS) -> list[str]:
    """Return schema errors with JSON paths, or an empty list for valid input."""
    return sorted(
        f"{error.json_path}: {error.message}"
        for error in schema_validator(directory).iter_errors(document)
    )


def main() -> int:
    """Validate the provided SBOM and return a failing status for any violation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    errors = validate_sbom(json.loads(args.input.read_text()))
    if errors:
        print("\n".join(errors))
        return 1
    print("CycloneDX 1.5 schema validation passed (offline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
