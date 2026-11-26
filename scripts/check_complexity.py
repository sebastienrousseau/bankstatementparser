#!/usr/bin/env python3
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Hold every Python function under the suite's complexity ceilings.

Ceilings per function: cyclomatic 10, cognitive 15, Halstead difficulty
30, 60 lines; and 500 lines per file. Functions that were already over
a ceiling when this gate arrived are listed in a committed baseline.
They may not get worse, and an entry that improves or disappears must
be recorded (``--update``), so the baseline only ever shrinks.

The metrics are computed with the standard library alone, so the same
file runs unchanged in every repository of the suite:

* cyclomatic: radon's counting (one per branch point, loop, handler,
  boolean operand, comprehension clause, assert and match case);
* cognitive: SonarSource's definition (increments for breaks in linear
  flow, plus their nesting depth; one per run of boolean operators);
* Halstead difficulty: radon's operator and operand definition;
* lines: from the ``def`` line to the last line of the body.

Each nested function is also measured on its own. As in the reference
tools, it also counts towards the function that contains it for
cognitive complexity (one level deeper) and Halstead difficulty, but
not for cyclomatic complexity. A recursive call adds one to cognitive
complexity, and a comprehension nests what it contains.

Cross-checked on the core package (764 functions): cyclomatic matches
radon 6.0.1 on every function; cognitive matches complexipy 9.0.0 on
all but a few percent, never by more than three points;
Halstead difficulty matches radon on 490 of 495 functions.

Usage::

    python3 scripts/check_complexity.py            # gate
    python3 scripts/check_complexity.py --report   # every offender
    python3 scripts/check_complexity.py --update   # record a shrink
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

CEILINGS = {
    "cyclomatic": 10,
    "cognitive": 15,
    "halstead": 30,
    "lines": 60,
}
FILE_CEILING = 500
BASELINE = Path("scripts/complexity_baseline.json")
SKIP_DIRS = {
    "build",
    "dist",
    "node_modules",
    "site",
    "site-packages",
    "venv",
    "__pycache__",
}

FuncNode = ast.FunctionDef | ast.AsyncFunctionDef
Metrics = dict[str, dict[str, float]]
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
LOOPS = (ast.For, ast.AsyncFor, ast.While)
# Constructs that add no increment of their own but nest what is in them.
NESTING = (
    ast.Lambda,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


# ---------------------------------------------------------------------------
# Cyclomatic complexity
# ---------------------------------------------------------------------------
def _cyclomatic_step(node: ast.AST) -> int:
    if isinstance(node, (ast.If, ast.IfExp, ast.Assert)):
        return 1
    if isinstance(node, LOOPS):
        return 1 + bool(node.orelse)
    if isinstance(node, ast.Try):
        return len(node.handlers) + bool(node.orelse)
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    if isinstance(node, ast.match_case):
        return 1
    return 0


def cyclomatic(func: FuncNode) -> int:
    """Return radon-style cyclomatic complexity of ``func``."""
    return 1 + sum(_cyclomatic_step(n) for n in _own_nodes(func))


def _own_nodes(func: FuncNode) -> Iterator[ast.AST]:
    """Yield the nodes of ``func``'s body, not of scopes nested in it."""
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, SCOPES):
            stack.extend(ast.iter_child_nodes(node))


# ---------------------------------------------------------------------------
# Cognitive complexity (SonarSource)
# ---------------------------------------------------------------------------
@dataclass
class _Cognitive:
    name: str
    method: bool
    total: int = 0

    def body(self, nodes: list[ast.stmt], depth: int) -> None:
        for node in nodes:
            self.visit(node, depth)

    def visit(self, node: ast.AST, depth: int) -> None:
        if isinstance(node, ast.If):
            self.total += 1 + depth
            self._if_chain(node, depth)
        elif isinstance(node, (*LOOPS, ast.Match)):
            self.total += 1 + depth
            self._nested_children(node, depth)
        elif isinstance(node, ast.Try):
            self._try(node, depth)
        elif isinstance(node, ast.IfExp):
            self.total += 1 + depth
            self._nested_children(node, depth)
        elif isinstance(node, NESTING):
            self._nested_children(node, depth)
        elif isinstance(node, ast.ClassDef):
            return
        else:
            self._expression(node, depth)

    def _expression(self, node: ast.AST, depth: int) -> None:
        if isinstance(node, ast.BoolOp):
            self.total += 1 + _operator_switches(node)
        elif (
            isinstance(node, ast.Call)
            and _callee(node, self.method) == self.name
        ):
            self.total += 1
        for child in ast.iter_child_nodes(node):
            self.visit(child, depth)

    def _nested_children(self, node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            self.visit(child, depth + 1)

    def _if_chain(self, node: ast.If, depth: int) -> None:
        self.visit(node.test, depth)
        self.body(node.body, depth + 1)
        orelse = node.orelse
        while len(orelse) == 1 and isinstance(orelse[0], ast.If):
            elif_node = orelse[0]
            self.total += 1
            self.visit(elif_node.test, depth)
            self.body(elif_node.body, depth + 1)
            orelse = elif_node.orelse
        if orelse:
            self.total += 1
            self.body(orelse, depth + 1)

    def _try(self, node: ast.Try, depth: int) -> None:
        self.body(node.body, depth)
        for handler in node.handlers:
            self.total += 1 + depth
            self.body(handler.body, depth + 1)
        self.body(node.orelse, depth)
        self.body(node.finalbody, depth)


def _operator_switches(node: ast.BoolOp) -> int:
    """Count nested boolean operators that differ from their parent's.

    ``a and b and c`` is one sequence; ``a and b or c`` is two. The
    outer node is counted by the caller and each operand that is
    itself a ``BoolOp`` is reached later by the visitor, so this only
    corrects for operands of the *same* operator, which are one run.
    """
    return -sum(
        1
        for value in node.values
        if isinstance(value, ast.BoolOp) and type(value.op) is type(node.op)
    )


def _callee(call: ast.Call, method: bool) -> str | None:
    """Name the function ``call`` would recurse into, if it could.

    Inside a method only ``self.x()`` or ``cls.x()`` reaches the method
    itself; a bare ``x()`` there is a module-level function.
    """
    func = call.func
    if isinstance(func, ast.Name):
        return None if method else func.id
    if not (method and isinstance(func, ast.Attribute)):
        return None
    receiver = func.value
    if isinstance(receiver, ast.Name) and receiver.id in {"self", "cls"}:
        return func.attr
    return None


def _is_method(func: FuncNode) -> bool:
    first = func.args.posonlyargs + func.args.args
    return bool(first) and first[0].arg in {"self", "cls"}


def cognitive(func: FuncNode) -> int:
    """Return SonarSource cognitive complexity of ``func``."""
    counter = _Cognitive(func.name, _is_method(func))
    counter.body(func.body, 0)
    return counter.total


# ---------------------------------------------------------------------------
# Halstead difficulty (radon's operator and operand set)
# ---------------------------------------------------------------------------
@dataclass
class _Halstead:
    operators: set[str] = field(default_factory=set)
    operands: set[object] = field(default_factory=set)
    operand_count: int = 0

    def add(self, ops: list[ast.AST], operands: list[ast.AST]) -> None:
        self.operators.update(type(op).__name__ for op in ops)
        self.operands.update(_operand_key(o) for o in operands)
        self.operand_count += len(operands)

    def difficulty(self) -> float:
        if not self.operands:
            return 0.0
        distinct = len(self.operands)
        return len(self.operators) * self.operand_count / (2 * distinct)


def _operand_key(node: ast.AST) -> object:
    """Identify an operand the way radon does.

    Names, attributes and constants are the same operand wherever they
    appear; any other expression is an operand of its own.
    """
    if isinstance(node, ast.Name):
        return ("name", node.id)
    if isinstance(node, ast.Attribute):
        return ("name", node.attr)
    if isinstance(node, ast.Constant):
        return ("constant", repr(node.value))
    return ("node", id(node))


def _halstead_parts(node: ast.AST) -> tuple[list[ast.AST], list[ast.AST]]:
    if isinstance(node, ast.BinOp):
        return [node.op], [node.left, node.right]
    if isinstance(node, ast.UnaryOp):
        return [node.op], [node.operand]
    if isinstance(node, ast.BoolOp):
        return [node.op], list(node.values)
    if isinstance(node, ast.AugAssign):
        return [node.op], [node.target, node.value]
    if isinstance(node, ast.Compare):
        return list(node.ops), [*node.comparators, node.left]
    return [], []


def halstead(func: FuncNode) -> float:
    """Return the Halstead difficulty of ``func``, nested code included."""
    counter = _Halstead()
    for statement in func.body:
        for node in ast.walk(statement):
            counter.add(*_halstead_parts(node))
    return round(counter.difficulty(), 2)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
def _functions(
    tree: ast.AST, prefix: str = ""
) -> Iterator[tuple[str, FuncNode]]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}{node.name}"
            yield name, node
            yield from _functions(node, f"{name}.")
        elif isinstance(node, ast.ClassDef):
            yield from _functions(node, f"{prefix}{node.name}.")
        else:
            yield from _functions(node, prefix)


def measure(func: FuncNode) -> dict[str, float]:
    """Return every per-function metric for ``func``."""
    end = func.end_lineno or func.lineno
    return {
        "cyclomatic": cyclomatic(func),
        "cognitive": cognitive(func),
        "halstead": halstead(func),
        "lines": end - func.lineno + 1,
    }


def _python_files(roots: list[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        for path in sorted(root.rglob("*.py")):
            parts = path.relative_to(root).parts[:-1]
            if any(p in SKIP_DIRS or p.startswith(".") for p in parts):
                continue
            if any(p.endswith(".egg-info") for p in parts):
                continue
            yield path


def offenders(roots: list[Path]) -> Metrics:
    """Return ``{key: {metric: value}}`` for everything over a ceiling."""
    found: Metrics = {}
    for path in _python_files(roots):
        source = path.read_text(encoding="utf-8")
        rel = path.as_posix()
        if source.count("\n") > FILE_CEILING:
            found[rel] = {"file_lines": source.count("\n")}
        tree = ast.parse(source, filename=rel)
        for name, func in _functions(tree):
            over = {
                metric: value
                for metric, value in measure(func).items()
                if value > CEILINGS[metric]
            }
            if over:
                key = _unique(found, f"{rel}::{name}")
                found[key] = over
    return found


def _unique(found: Metrics, key: str) -> str:
    candidate, n = key, 1
    while candidate in found:
        n += 1
        candidate = f"{key}#{n}"
    return candidate


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------
def _flatten(table: Metrics) -> dict[tuple[str, str], float]:
    return {
        (key, metric): value
        for key, metrics in table.items()
        for metric, value in metrics.items()
    }


def compare(
    current: Metrics, baseline: Metrics
) -> tuple[list[str], list[str]]:
    """Return (regressions, improvements) of ``current`` vs ``baseline``."""
    now = _flatten(current)
    allowed = _flatten(baseline)
    worse = [
        f"{key}: {metric} {value} is a new offender"
        if (key, metric) not in allowed
        else f"{key}: {metric} {value} > baseline {allowed[key, metric]}"
        for (key, metric), value in sorted(now.items())
        if value > allowed.get((key, metric), value - 1)
    ]
    better = [
        f"{key}: {metric} {limit} -> {now.get((key, metric), 'under ceiling')}"
        for (key, metric), limit in sorted(allowed.items())
        if now.get((key, metric), limit - 1) < limit
    ]
    return worse, better


def _load(path: Path) -> Metrics | None:
    if not path.exists():
        return None
    data: Metrics = json.loads(path.read_text(encoding="utf-8"))
    return data


def _write(path: Path, data: Metrics) -> None:
    text = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def _report(current: Metrics) -> int:
    def weight(item: tuple[str, dict[str, float]]) -> float:
        return max(
            v / CEILINGS.get(m, FILE_CEILING) for m, v in item[1].items()
        )

    for key, metrics in sorted(current.items(), key=weight, reverse=True):
        shown = ", ".join(f"{m} {v}" for m, v in sorted(metrics.items()))
        print(f"{key}: {shown}")
    print(f"{len(current)} offender(s)")
    return 0


def _update(
    current: Metrics,
    baseline: Metrics | None,
) -> int:
    if baseline is not None:
        worse, _ = compare(current, baseline)
        if worse:
            print("refusing to grow the baseline:", *worse, sep="\n  ")
            return 1
    _write(BASELINE, current)
    print(f"wrote {BASELINE} ({len(current)} offender(s))")
    return 0


def _gate(
    current: Metrics,
    baseline: Metrics | None,
) -> int:
    if baseline is None:
        print(f"{BASELINE} is missing; create it with --update")
        return 1
    worse, better = compare(current, baseline)
    if worse:
        print("complexity regressions:", *worse, sep="\n  ")
    if better:
        print(
            "improvements not yet recorded (run with --update):",
            *better,
            sep="\n  ",
        )
    if worse or better:
        return 1
    print(f"complexity: {len(current)} baselined offender(s), none worse")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the gate, the report or the baseline update."""
    parser = argparse.ArgumentParser(description="Complexity gate")
    parser.add_argument("roots", nargs="*", type=Path, default=[Path()])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report", action="store_true")
    mode.add_argument("--update", action="store_true")
    args = parser.parse_args(argv)
    current = offenders(args.roots)
    if args.report:
        return _report(current)
    baseline = _load(BASELINE)
    if args.update:
        return _update(current, baseline)
    return _gate(current, baseline)


if __name__ == "__main__":
    sys.exit(main())
