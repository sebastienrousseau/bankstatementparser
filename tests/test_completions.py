"""Tests for ``scripts/generate_completions.py`` and the committed completions."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "generate_completions.py"
)


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    """Load the generator script as a module."""
    spec = importlib.util.spec_from_file_location("gen_completions", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_completions_match_the_parsers(
    generator: ModuleType,
) -> None:
    """Every committed completion is what the parsers generate today."""
    assert generator.stale(generator.render()) == []
    assert generator.main(["--check"]) == 0


def test_completions_carry_every_cli_flag(generator: ModuleType) -> None:
    """The bash completion offers the CLI's flags and --type choices."""
    files = generator.render()
    bash = files[generator.OUT_DIR / "bankstatementparser.bash"]
    for flag in ("--type", "--input", "--output", "--streaming", "--show-pii"):
        assert flag in bash
    for choice in ("camt", "pain001", "ingest", "review"):
        assert choice in bash
    api = files[generator.OUT_DIR / "bankstatementparser-api.bash"]
    assert "--host" in api and "--port" in api


def test_check_reports_a_stale_file(
    generator: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--check`` fails and names the file when a completion is missing."""
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(generator, "OUT_DIR", tmp_path / "completions")
    assert generator.main(["--check"]) == 1
    assert "stale: completions/" in capsys.readouterr().err
    assert generator.main([]) == 0
    assert generator.main(["--check"]) == 0
