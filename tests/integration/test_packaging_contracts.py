# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Locked marker projection and offline artifact-validation contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.markers import Marker, default_environment
from packaging.requirements import Requirement
from scripts.export_locked_requirements import (
    export_requirements,
    project_extras,
)
from scripts.validate_sbom import SCHEMAS, validate_sbom

ROOT = Path(__file__).resolve().parents[2]


def _lock() -> dict:
    return {
        "metadata": {"lock-version": "2.1", "python-versions": ">=3.10,<4.0"},
        "extras": {"api": [], "hybrid": []},
        "package": [
            {
                "name": "annotated-doc",
                "version": "0.0.4",
                "groups": ["main"],
                "python-versions": ">=3.8",
                "markers": '(extra == "api" or python_version < "3.14") and (extra == "api" or extra == "hybrid")',
                "files": [{"hash": "sha256:" + "a" * 64}],
            }
        ],
    }


@pytest.mark.parametrize(
    "extras", [set(), {"api"}, {"hybrid"}, {"api", "hybrid"}]
)
@pytest.mark.parametrize("version", ["3.10", "3.14"])
def test_extra_projection_preserves_python_alternatives(
    extras, version
) -> None:
    lock = _lock()
    text = export_requirements(lock, {"main"}, extras)
    selected = [
        line.removesuffix(" \\")
        for line in text.splitlines()
        if line.startswith("annotated-doc")
    ]
    environment = {
        **default_environment(),
        "python_version": version,
        "python_full_version": version + ".1",
    }
    actual = bool(
        selected and Requirement(selected[0]).marker.evaluate(environment)
    )
    original = Marker(lock["package"][0]["markers"])
    expected = any(
        original.evaluate({**environment, "extra": extra})
        for extra in (extras or {""})
    )
    assert actual == expected
    if selected:
        assert "--hash=sha256:" + "a" * 64 in text
        assert "extra ==" not in selected[0]


@pytest.mark.parametrize(
    "marker,extras,expected",
    [
        ('extra != "api"', {"api", "hybrid"}, False),
        ('extra != "api"', {"hybrid"}, True),
        ('"api" == extra', {"api"}, True),
        ('extra in "api,hybrid"', {"hybrid"}, True),
        ('extra not in "api,hybrid"', set(), False),
        (
            'extra == "api" and (sys_platform == "win32" or python_version >= "3.14")',
            {"api"},
            '(sys_platform == "win32" or python_version >= "3.14")',
        ),
    ],
)
def test_extra_projection_boolean_and_operand_semantics(
    marker, extras, expected
) -> None:
    projected = project_extras(marker, extras)
    if isinstance(expected, bool):
        assert projected is expected
    else:
        for platform in ["win32", "linux"]:
            for version in ["3.10", "3.14"]:
                environment = {
                    **default_environment(),
                    "sys_platform": platform,
                    "python_version": version,
                }
                assert Marker(projected).evaluate(environment) == Marker(
                    expected
                ).evaluate(environment)


def test_exporter_group_markers_and_unconditional_packages() -> None:
    lock = _lock()
    package = lock["package"][0]
    package["groups"] = ["main", "dev"]
    package["markers"] = {"main": 'extra == "api"', "dev": ""}
    package["python-versions"] = "*"
    assert "annotated-doc" in export_requirements(lock, {"main", "dev"}, set())
    assert "annotated-doc" not in export_requirements(lock, {"main"}, set())
    with pytest.raises(ValueError, match="Unknown requested"):
        export_requirements(lock, {"unknown"}, set())
    with pytest.raises(ValueError, match="Unknown requested"):
        export_requirements(lock, {"main"}, {"unknown"})


def test_exporter_rejects_unsupported_or_unhashed_inputs() -> None:
    with pytest.raises(ValueError, match="Unsupported comparison"):
        project_extras('extra >= "1"', {"api"})
    for change, error in [
        ({"source": {"type": "git"}}, "Non-PyPI"),
        ({"files": []}, "hashes"),
        ({"files": [{"hash": "md5:abc"}]}, "hashes"),
    ]:
        lock = _lock()
        lock["package"][0].update(change)
        with pytest.raises(ValueError, match=error):
            export_requirements(lock, {"main"}, {"api"})
    lock = _lock()
    lock["metadata"]["lock-version"] = "2.0"
    with pytest.raises(ValueError, match="lock format"):
        export_requirements(lock, {"main"}, set())


def test_generated_requirements_are_current_and_cli_exports_all_extras(
    tmp_path,
) -> None:
    output = tmp_path / "requirements.txt"
    script = ROOT / "scripts" / "export_locked_requirements.py"
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--with",
            "dev",
            "--output",
            str(output),
        ],
        check=True,
    )
    assert output.read_bytes() == (ROOT / "requirements.txt").read_bytes()
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--with",
            "dev",
            "--all-extras",
            "--output",
            str(output),
        ],
        check=True,
    )
    requirement = next(
        Requirement(line.removesuffix(" \\"))
        for line in output.read_text().splitlines()
        if line.startswith("annotated-doc==")
    )
    assert requirement.marker.evaluate(
        {
            **default_environment(),
            "python_version": "3.14",
            "python_full_version": "3.14.1",
        }
    )


def test_official_sbom_schema_validates_generated_artifact_and_rejects_errors(
    tmp_path,
) -> None:
    output = tmp_path / "sbom.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_sbom.py"),
            "--output",
            str(output),
            "--markdown-output",
            str(tmp_path / "report.md"),
        ],
        check=True,
    )
    document = json.loads(output.read_text())
    assert validate_sbom(document) == []
    script = ROOT / "scripts" / "validate_sbom.py"
    subprocess.run([sys.executable, str(script), str(output)], check=True)
    invalid = copy.deepcopy(document)
    invalid["serialNumber"] = "not-a-uuid"
    invalid["components"][0]["properties"] = [{"name": "markers", "value": {}}]
    errors = validate_sbom(invalid)
    assert any("serialNumber" in error for error in errors)
    assert any("components" in error for error in errors)
    output.write_text(json.dumps(invalid))
    assert (
        subprocess.run(
            [sys.executable, str(script), str(output)], capture_output=True
        ).returncode
        == 1
    )


def test_schema_integrity_rejects_local_modifications(tmp_path) -> None:
    directory = tmp_path / "schemas"
    shutil.copytree(SCHEMAS, directory)
    schema = directory / "bom-1.5.schema.json"
    schema.write_text("{}")
    assert (
        hashlib.sha256(schema.read_bytes()).hexdigest()
        not in (directory / "SHA256SUMS").read_text()
    )
    with pytest.raises(ValueError, match="integrity"):
        validate_sbom({}, directory)
