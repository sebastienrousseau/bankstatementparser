#!/usr/bin/env python3
"""Generate a CycloneDX-style SBOM from pyproject.toml and poetry.lock."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def load_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file and return its contents as a dictionary."""
    with path.open("rb") as handle:
        return cast(dict[str, Any], tomllib.load(handle))


def normalize_distribution_name(name: str) -> str:
    """Normalize a distribution name to lowercase with hyphens."""
    return name.replace("_", "-").lower()


def resolve_license(package_name: str) -> str:
    """Return the license for an installed package, or "UNKNOWN"."""
    normalized = normalize_distribution_name(package_name)
    try:
        metadata = importlib.metadata.metadata(normalized)
    except importlib.metadata.PackageNotFoundError:
        return "UNKNOWN"

    for key in ("License", "Classifier"):
        values = metadata.get_all(key)
        if not values:
            continue
        if key == "License":
            license_name = values[0].strip()
            if license_name:
                return license_name
        for value in values:
            if value.startswith("License ::"):
                return value.replace("License ::", "", 1).strip()
    return "UNKNOWN"


def package_ref(name: str, version: str) -> str:
    """Build a PyPI package URL (purl) reference for a package."""
    normalized = quote(normalize_distribution_name(name), safe="")
    return f"pkg:pypi/{normalized}@{version}"


def cyclonedx_component(package: dict[str, Any]) -> dict[str, Any]:
    """Build a CycloneDX component entry from a lock package."""
    name = package["name"]
    version = package["version"]
    hashes = []
    for file_entry in package.get("files", []):
        digest = file_entry.get("hash", "")
        if digest.startswith("sha256:"):
            hashes.append(
                {"alg": "SHA-256", "content": digest.split(":", 1)[1]}
            )

    groups = ",".join(package.get("groups", [])) or "runtime"
    license_name = resolve_license(name)

    component = {
        "type": "library",
        "bom-ref": package_ref(name, version),
        "name": name,
        "version": version,
        "purl": package_ref(name, version),
        "scope": "optional" if package.get("optional", False) else "required",
        "hashes": hashes,
        "properties": [
            {"name": "bankstatementparser:groups", "value": groups},
            {
                "name": "bankstatementparser:python-versions",
                "value": package.get("python-versions", ""),
            },
            {
                "name": "bankstatementparser:markers",
                "value": package.get("markers", ""),
            },
        ],
    }
    if license_name != "UNKNOWN":
        component["licenses"] = [{"license": {"name": license_name}}]
    return component


def build_dependency_edges(
    packages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build CycloneDX dependency edges between locked packages."""
    available_refs = {
        normalize_distribution_name(package["name"]): package_ref(
            package["name"], package["version"]
        )
        for package in packages
    }
    edges = []
    for package in packages:
        dependency_refs = []
        for dependency_name in package.get("dependencies", {}):
            ref = available_refs.get(
                normalize_distribution_name(dependency_name)
            )
            if ref is not None:
                dependency_refs.append(ref)
        edges.append(
            {
                "ref": package_ref(package["name"], package["version"]),
                "dependsOn": sorted(set(dependency_refs)),
            }
        )
    return edges


def build_sbom(
    pyproject: dict[str, Any],
    lock_data: dict[str, Any],
) -> dict[str, Any]:
    """Assemble a CycloneDX SBOM from pyproject and lock data."""
    poetry = pyproject["tool"]["poetry"]
    packages = lock_data.get("package", [])
    components = [cyclonedx_component(package) for package in packages]
    dependencies = build_dependency_edges(packages)

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": (
            "urn:uuid:bankstatementparser-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        ),
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": [
                {
                    "vendor": "bankstatementparser",
                    "name": "generate_sbom.py",
                    "version": "1.0.0",
                }
            ],
            "component": {
                "type": "application",
                "name": poetry["name"],
                "version": poetry["version"],
                "licenses": [
                    {"license": {"name": poetry.get("license", "UNKNOWN")}}
                ],
                "externalReferences": [
                    {
                        "type": "vcs",
                        "url": poetry.get("repository", ""),
                    },
                    {
                        "type": "website",
                        "url": poetry.get("homepage", ""),
                    },
                ],
            },
        },
        "components": components,
        "dependencies": dependencies,
    }


def write_markdown_report(
    packages: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write a Markdown dependency report for the locked packages."""
    lines = [
        "# Dependency Report",
        "",
        "| Package | Version | Groups | License | SHA256 Hashes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for package in sorted(packages, key=lambda item: item["name"].lower()):
        hashes = [
            entry["hash"].split(":", 1)[1]
            for entry in package.get("files", [])
            if entry.get("hash", "").startswith("sha256:")
        ]
        lines.append(
            "| {name} | {version} | {groups} | {license_name} | {hash_count} |".format(
                name=package["name"],
                version=package["version"],
                groups=", ".join(package.get("groups", [])) or "runtime",
                license_name=resolve_license(package["name"]),
                hash_count=len(hashes),
            )
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the SBOM generator."""
    parser = argparse.ArgumentParser(
        description="Generate a CycloneDX-style SBOM and dependency report."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "sbom.cyclonedx.json",
        help="Path to the generated SBOM JSON file.",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=ROOT / "artifacts" / "dependency-report.md",
        help="Path to the generated dependency report in Markdown.",
    )
    return parser.parse_args()


def main() -> int:
    """Generate the SBOM JSON and Markdown dependency report files."""
    args = parse_args()
    pyproject = load_toml(ROOT / "pyproject.toml")
    lock_data = load_toml(ROOT / "poetry.lock")
    sbom = build_sbom(pyproject, lock_data)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
    write_markdown_report(lock_data.get("package", []), args.markdown_output)
    print(f"SBOM written to {args.output}")
    print(f"Dependency report written to {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
