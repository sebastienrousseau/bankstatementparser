"""Tests for ``scripts/check_complexity.py``, the suite's complexity gate."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "check_complexity.py"
)

# The expected numbers for ``nested``, ``comp`` and ``loop`` come from
# radon 6.0.1 (cyclomatic, Halstead) and complexipy 9.0.0 (cognitive).
SAMPLE = """
def nested(xs, y):
    for x in xs:
        if x and y or not x:
            try:
                pass
            except ValueError:
                continue
        elif x > 3:
            pass
        else:
            return 1
    return 0


def recurse(n):
    return n if n < 2 else recurse(n - 1) + recurse(n - 2)


def comp(xs):
    return [x for x in xs if x % 2 == 0]


def loop(x):
    while x:
        x -= 1
    else:
        return 0


class Box:
    def size(self):
        return size(self)
"""


@pytest.fixture(scope="module")
def cc() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_complexity", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _measured(cc: ModuleType) -> dict[str, dict[str, float]]:
    tree = ast.parse(SAMPLE)
    return {name: cc.measure(func) for name, func in cc._functions(tree)}


def test_metrics_match_the_reference_tools(cc: ModuleType) -> None:
    measured = _measured(cc)
    assert measured["nested"] == {
        "cyclomatic": 7,
        "cognitive": 10,
        "halstead": 2.8,
        "lines": 12,
    }
    assert measured["comp"]["cyclomatic"] == 3
    assert measured["loop"]["cyclomatic"] == 3
    assert measured["comp"]["halstead"] == 1.0


def test_each_recursive_call_adds_cognitive_complexity(cc: ModuleType) -> None:
    # One for the conditional expression, one per recursive call.
    assert _measured(cc)["recurse"]["cognitive"] == 3


def test_a_method_calling_a_same_named_function_is_not_recursion(
    cc: ModuleType,
) -> None:
    assert _measured(cc)["Box.size"]["cognitive"] == 0


def _write_module(root: Path, body: str) -> None:
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "mod.py").write_text(body, encoding="utf-8")


def _branchy(count: int) -> str:
    lines = ["def f(x):"]
    lines += [f"    if x == {i}:\n        return {i}" for i in range(count)]
    return "\n".join([*lines, "    return -1", ""])


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text(_branchy(30))
    return tmp_path


def test_missing_baseline_fails(cc: ModuleType, repo: Path) -> None:
    _write_module(repo, _branchy(2))
    assert cc.main([]) == 1


def test_update_then_gate_passes(cc: ModuleType, repo: Path) -> None:
    _write_module(repo, _branchy(12))
    assert cc.main(["--update"]) == 0
    baseline = json.loads((repo / cc.BASELINE).read_text())
    assert baseline == {"pkg/mod.py::f": {"cyclomatic": 13}}
    assert cc.main([]) == 0


def test_a_new_offender_fails(cc: ModuleType, repo: Path) -> None:
    _write_module(repo, _branchy(2))
    assert cc.main(["--update"]) == 0
    _write_module(repo, _branchy(12))
    assert cc.main([]) == 1


def test_a_worse_offender_fails_and_update_refuses(
    cc: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_module(repo, _branchy(12))
    assert cc.main(["--update"]) == 0
    _write_module(repo, _branchy(14))
    assert cc.main([]) == 1
    assert "> baseline 13" in capsys.readouterr().out
    assert cc.main(["--update"]) == 1
    assert "refusing to grow" in capsys.readouterr().out


def test_an_improvement_must_be_recorded(
    cc: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_module(repo, _branchy(14))
    assert cc.main(["--update"]) == 0
    _write_module(repo, _branchy(2))
    assert cc.main([]) == 1
    assert "under ceiling" in capsys.readouterr().out
    assert cc.main(["--update"]) == 0
    assert json.loads((repo / cc.BASELINE).read_text()) == {}
    assert cc.main([]) == 0


def test_long_files_are_offenders(cc: ModuleType, repo: Path) -> None:
    _write_module(repo, "x = 1\n" * 501)
    assert cc.offenders([Path()]) == {"pkg/mod.py": {"file_lines": 501}}


def test_report_lists_offenders_worst_first(
    cc: ModuleType, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_module(repo, _branchy(12) + _branchy(20).replace("def f", "def g"))
    assert cc.main(["--report"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("pkg/mod.py::g")
    assert out[-1] == "2 offender(s)"
