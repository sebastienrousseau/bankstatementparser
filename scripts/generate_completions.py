# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
#
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generate shell completions for the two console scripts.

The completions are derived with ``shtab`` from the same argparse
parsers the commands parse with (``BankStatementCLI.setup_arg_parser``
and ``api.build_arg_parser``), so a new flag reaches the completions by
regenerating them, never by hand.

Run from the project environment (``poetry install --with dev``)::

    python scripts/generate_completions.py          # write completions/
    python scripts/generate_completions.py --check  # fail if stale (CI)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

import shtab

from bankstatementparser.api import build_arg_parser
from bankstatementparser.cli import BankStatementCLI

ROOT = Path(__file__).resolve().parent.parent

OUT_DIR = ROOT / "completions"
SHELLS = ("bash", "zsh", "tcsh")
SUFFIX = {"bash": ".bash", "zsh": ".zsh", "tcsh": ".tcsh"}

PARSERS: dict[str, Callable[[], argparse.ArgumentParser]] = {
    "bankstatementparser": lambda: BankStatementCLI().setup_arg_parser(),
    "bankstatementparser-api": build_arg_parser,
}


def _parser_for(prog: str) -> argparse.ArgumentParser:
    """Build ``prog``'s parser, named as the console script installs it.

    argparse names a parser after ``sys.argv[0]`` unless told otherwise,
    which here would be this script.
    """
    parser = PARSERS[prog]()
    parser.prog = prog
    return parser


def render() -> dict[Path, str]:
    """Return every completion file's path and its generated text."""
    files: dict[Path, str] = {}
    for prog in PARSERS:
        for shell in SHELLS:
            name = prog if shell != "zsh" else f"_{prog}"
            path = OUT_DIR / f"{name}{SUFFIX[shell]}"
            files[path] = shtab.complete(_parser_for(prog), shell)
    return files


def stale(files: dict[Path, str]) -> list[Path]:
    """Return the files whose committed text differs from ``files``."""
    return [
        path
        for path, text in files.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != text
    ]


def main(argv: list[str] | None = None) -> int:
    """Write the completions, or with ``--check`` report stale ones."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when a committed completion differs from the parser",
    )
    args = parser.parse_args(argv)
    files = render()
    if args.check:
        outdated = stale(files)
        for path in outdated:
            print(
                f"stale: {path.relative_to(ROOT).as_posix()}", file=sys.stderr
            )
        if outdated:
            print("run: make completions", file=sys.stderr)
        return 1 if outdated else 0
    OUT_DIR.mkdir(exist_ok=True)
    for path, text in files.items():
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
