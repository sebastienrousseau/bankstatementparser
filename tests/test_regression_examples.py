# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Regression suite: execute every shipped example script end-to-end.

Each example under ``examples/`` (including ``examples/hybrid/``) is run
as a real subprocess against the repository fixtures, exactly as a user
would run it. A script that crashes, prints an error, or drifts away
from the current public API fails the suite.

Examples that need optional extras (reportlab, pypdfium2, pypdf, PIL)
are skipped when those extras are not installed, never silently passed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
HYBRID_DIR = EXAMPLES_DIR / "hybrid"
SAMPLE_DATA_DIR = HYBRID_DIR / "sample_data"

CAMT_FIXTURE = REPO_ROOT / "tests" / "test_data" / "camt.053.001.02.xml"
PAIN001_FIXTURE = REPO_ROOT / "tests" / "test_data" / "pain.001.001.03.xml"


def _has(module: str) -> bool:
    return find_spec(module) is not None


def _run(
    *command: str,
    stdin: str | None = None,
    timeout: int = 180,
) -> str:
    env = os.environ.copy()
    # Console scripts (e.g. `bankstatementparser`) live next to the
    # interpreter; shell examples rely on them being on PATH.
    env["PATH"] = (
        str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    )
    proc = subprocess.run(
        list(command),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        input=stdin,
        timeout=timeout,
        env=env,
    )
    assert proc.returncode == 0, (
        f"{' '.join(command)} exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return proc.stdout


def _run_example(script: Path, *args: str, stdin: str | None = None) -> str:
    return _run(sys.executable, str(script), *args, stdin=stdin)


def _bash() -> str:
    """Locate a real bash for the shell-script examples.

    On Windows, plain ``bash`` resolves to the System32 WSL launcher,
    which exits 1 when no WSL distribution is installed (the GitHub
    runner default). Git Bash ships with git, so derive its path from
    ``git.exe`` instead.
    """
    if sys.platform != "win32":
        return "bash"
    git = shutil.which("git")
    if git:
        candidate = Path(git).resolve().parents[1] / "bin" / "bash.exe"
        if candidate.exists():
            return str(candidate)
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    pytest.skip("no usable bash on this Windows host")


# ----------------------------------------------------------------------
# Deterministic examples (no optional extras required)
# ----------------------------------------------------------------------


def test_parse_camt_basic() -> None:
    out = _run_example(EXAMPLES_DIR / "parse_camt_basic.py")
    assert "Transactions parsed:" in out


def test_parse_camt_from_string() -> None:
    out = _run_example(EXAMPLES_DIR / "parse_camt_from_string.py")
    assert "Parsed from string:" in out


def test_parse_pain001_basic() -> None:
    out = _run_example(EXAMPLES_DIR / "parse_pain001_basic.py")
    assert "Payments parsed:" in out


def test_parse_detected_formats() -> None:
    out = _run_example(EXAMPLES_DIR / "parse_detected_formats.py")
    for fixture in ("sample_statement.csv", "sample.ofx", "sample.mt940"):
        assert fixture in out


def test_parse_camt_zip_build_then_parse(tmp_path: Path) -> None:
    zip_path = tmp_path / "camt-demo.zip"
    script = EXAMPLES_DIR / "parse_camt_zip.py"
    build_out = _run_example(script, "--build-demo-zip", str(zip_path))
    assert "Demo ZIP created at" in build_out
    parse_out = _run_example(script, str(zip_path))
    assert "transactions parsed" in parse_out


def test_stream_camt() -> None:
    out = _run_example(EXAMPLES_DIR / "stream_camt.py")
    assert "Transaction 1" in out


def test_stream_pain001() -> None:
    out = _run_example(EXAMPLES_DIR / "stream_pain001.py")
    assert "Payment 1" in out


def test_inspect_camt() -> None:
    out = _run_example(EXAMPLES_DIR / "inspect_camt.py")
    assert "Balances" in out
    assert "Summary" in out


def test_validate_input() -> None:
    out = _run_example(EXAMPLES_DIR / "validate_input.py")
    assert "Validated:" in out
    assert "Rejected:" in out


def test_compatibility_wrappers() -> None:
    out = _run_example(EXAMPLES_DIR / "compatibility_wrappers.py")
    assert out.strip()


def test_export_camt(tmp_path: Path) -> None:
    out = _run_example(
        EXAMPLES_DIR / "export_camt.py", "--output-dir", str(tmp_path)
    )
    assert "CSV exported to" in out
    assert "JSON exported to" in out
    assert list(tmp_path.glob("*.csv"))
    assert list(tmp_path.glob("*.json"))


def test_export_pain001(tmp_path: Path) -> None:
    out = _run_example(
        EXAMPLES_DIR / "export_pain001.py", "--output-dir", str(tmp_path)
    )
    assert "CSV exported to" in out
    assert "JSON exported to" in out
    assert list(tmp_path.glob("*.csv"))
    assert list(tmp_path.glob("*.json"))


@pytest.mark.skipif(not _has("openpyxl"), reason="requires the excel extra")
def test_export_camt_excel() -> None:
    out = _run_example(EXAMPLES_DIR / "export_camt_excel.py")
    assert "Excel workbook written to" in out


def test_cli_examples_shell_script() -> None:
    _run(_bash(), str(EXAMPLES_DIR / "cli_examples.sh"))


# ----------------------------------------------------------------------
# Hybrid pipeline examples
# ----------------------------------------------------------------------


def test_hybrid_01_smart_ingest_deterministic() -> None:
    out = _run_example(HYBRID_DIR / "01_smart_ingest_deterministic.py")
    assert "Source method:    deterministic" in out


def test_hybrid_04_golden_rule() -> None:
    out = _run_example(HYBRID_DIR / "04_golden_rule.py")
    assert "VERIFIED" in out
    assert "DISCREPANCY" in out
    assert "FAILED" in out


def test_hybrid_05_dedupe_recurring() -> None:
    out = _run_example(HYBRID_DIR / "05_dedupe_recurring.py")
    assert "normalize_description() strips noise" in out


_PDF_GEN_DEPS = ("reportlab", "pypdfium2", "PIL")


def _ensure_sample_pdfs() -> None:
    """Generate the sample PDFs when absent (they are gitignored)."""
    digital = SAMPLE_DATA_DIR / "digital.pdf"
    scanned = SAMPLE_DATA_DIR / "scanned.pdf"
    if digital.exists() and scanned.exists():
        return
    missing = [dep for dep in _PDF_GEN_DEPS if not _has(dep)]
    if missing:
        pytest.skip(
            "sample PDFs absent and generator deps missing: "
            + ", ".join(missing)
        )
    _run_example(HYBRID_DIR / "generate_sample_pdfs.py")


@pytest.mark.skipif(
    any(not _has(dep) for dep in _PDF_GEN_DEPS),
    reason="requires reportlab, pypdfium2, and Pillow",
)
def test_hybrid_generate_sample_pdfs() -> None:
    _run_example(HYBRID_DIR / "generate_sample_pdfs.py")
    assert (SAMPLE_DATA_DIR / "digital.pdf").exists()
    assert (SAMPLE_DATA_DIR / "scanned.pdf").exists()


@pytest.mark.skipif(not _has("pypdf"), reason="requires the hybrid extra")
def test_hybrid_02_text_llm_mock_mode() -> None:
    _ensure_sample_pdfs()
    out = _run_example(HYBRID_DIR / "02_smart_ingest_text_llm.py")
    assert "Source method:    llm" in out


@pytest.mark.skipif(not _has("pypdf"), reason="requires the hybrid extra")
def test_hybrid_03_vision_mock_mode() -> None:
    _ensure_sample_pdfs()
    out = _run_example(HYBRID_DIR / "03_smart_ingest_vision.py")
    assert "Source method:    vision" in out


def test_hybrid_06_cli_walkthrough_shell() -> None:
    out = _run(_bash(), str(HYBRID_DIR / "06_cli_walkthrough.sh"))
    assert "Path A" in out
    assert "transaction_hash" in out
    assert (SAMPLE_DATA_DIR / "out.csv").exists()


def test_hybrid_06_powershell_walkthrough_mirrors_shell() -> None:
    """The .ps1 walkthrough must drive the same CLI surface as the .sh one."""
    ps1 = (HYBRID_DIR / "06_cli_walkthrough.ps1").read_text(encoding="utf-8")
    for needle in (
        "--type ingest",
        "BSP_HYBRID_MODEL",
        "BSP_HYBRID_VISION_MODEL",
    ):
        assert needle in ps1
