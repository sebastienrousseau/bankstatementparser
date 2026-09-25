#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Export hashed PyPI requirements from Poetry's resolved lock markers.

Poetry remains the resolver. This generator projects selected extras out of
lock markers before rendering requirements; deleting extra conditions from an
OR expression can otherwise drop a valid Python-version branch.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def _combine(values: list[bool | str], operator: str) -> bool | str:
    """Simplify a Boolean conjunction or disjunction without dropping truth."""
    absorbing = operator == "or"
    if any(value is absorbing for value in values):
        return absorbing
    residual = [value for value in values if isinstance(value, str)]
    if not residual:
        return not absorbing
    return f" {operator} ".join(f"({value})" for value in residual)


def _project_node(node: Any, extras: set[str]) -> bool | str:
    """Substitute extra atoms in packaging's parsed marker tree.

    The private marker tree is used only to preserve PEP 508 parsing and quote
    semantics. Regression tests cover Boolean precedence and both operand orders.
    Unsupported extra comparisons fail instead of silently widening selection.
    """
    if isinstance(node, tuple):
        left, operator, right = (term.serialize() for term in node)
        atom = f"{left} {operator} {right}"
        if "extra" not in (left, right):
            return atom
        if operator not in {"==", "!=", "in", "not in"}:
            raise ValueError("Unsupported comparison on an extra marker")
        matches = [
            Marker(atom).evaluate({"extra": extra})
            for extra in (extras or {""})
        ]
        return all(matches) if operator in {"!=", "not in"} else any(matches)
    groups: list[bool | str] = []
    conjunction: list[bool | str] = []
    for term in node:
        if term == "or":
            groups.append(_combine(conjunction, "and"))
            conjunction = []
        elif term != "and":
            conjunction.append(_project_node(term, extras))
    groups.append(_combine(conjunction, "and"))
    return _combine(groups, "or")


def project_extras(marker: str, extras: set[str]) -> bool | str:
    """Keep platform/Python conditions while evaluating the requested extras."""
    return _project_node(Marker(marker)._markers, extras) if marker else True


def python_marker(constraint: str) -> str:
    """Translate a locked PEP 440 Python range to a full-version marker."""
    if constraint == "*":
        return ""
    return " and ".join(
        f'python_full_version {specifier.operator} "{specifier.version}"'
        for specifier in sorted(SpecifierSet(constraint), key=str)
    )


def export_requirements(
    lock: dict[str, Any], groups: set[str], extras: set[str]
) -> str:
    """Render exact versions and all locked SHA-256 hashes for selected scopes.

    Requires Poetry lock 2.1 (resolved group/extra markers). Non-PyPI sources
    fail explicitly rather than being silently redirected to the public index.
    """
    if lock["metadata"]["lock-version"] != "2.1":
        raise ValueError("This exporter requires Poetry lock format 2.1")
    available_extras = set(lock.get("extras", {}))
    if extras - available_extras:
        raise ValueError("Unknown requested extras")
    available_groups = {
        group for package in lock["package"] for group in package["groups"]
    }
    if groups - available_groups:
        raise ValueError("Unknown requested dependency groups")
    project_python = python_marker(lock["metadata"]["python-versions"])
    lines = [
        "# Generated from poetry.lock by scripts/export_locked_requirements.py; do not edit."
    ]
    for package in sorted(
        lock["package"], key=lambda item: (item["name"], item["version"])
    ):
        selected_groups = groups.intersection(package["groups"])
        if not selected_groups:
            continue
        locked_marker = package.get("markers", "")
        markers = (
            [locked_marker.get(group, "") for group in sorted(selected_groups)]
            if isinstance(locked_marker, dict)
            else [locked_marker]
        )
        selected = _combine(
            [project_extras(marker, extras) for marker in markers], "or"
        )
        if selected is False:
            continue
        if package.get("source"):
            raise ValueError(
                "Non-PyPI lock sources require an explicit exporter implementation"
            )
        conditions = [
            project_python,
            python_marker(package["python-versions"]),
        ]
        if isinstance(selected, str):
            conditions.append(selected)
        marker_text = " and ".join(
            f"({condition})" for condition in conditions if condition
        )
        name = canonicalize_name(package["name"])
        requirement = str(Requirement(f"{name}=={package['version']}"))
        if marker_text:
            requirement += f" ; {Marker(marker_text)}"
        hashes = sorted({entry["hash"] for entry in package.get("files", [])})
        if not hashes or any(
            not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            for digest in hashes
        ):
            raise ValueError(
                f"Missing or unsupported locked hashes for {name}"
            )
        lines.append(requirement + " \\")
        lines.extend(
            f"    --hash={digest}" + (" \\" if index + 1 < len(hashes) else "")
            for index, digest in enumerate(hashes)
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    """Write a selected, hash-pinned requirements artifact from the project lock."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=ROOT / "poetry.lock")
    parser.add_argument("--with", dest="groups", action="append", default=[])
    parser.add_argument("-E", "--extra", action="append", default=[])
    parser.add_argument("--all-extras", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.lock.open("rb") as handle:
        lock = tomllib.load(handle)
    extras = (
        set(lock.get("extras", {}))
        if args.all_extras
        else {canonicalize_name(extra) for extra in args.extra}
    )
    groups = {
        "main",
        *(group for value in args.groups for group in value.split(",")),
    }
    args.output.write_text(
        export_requirements(lock, groups, extras),
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
