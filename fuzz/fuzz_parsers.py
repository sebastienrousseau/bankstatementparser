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
# See the License for the specific language governing permissions and
# limitations under the License.

"""Coverage-guided Atheris fuzz target for the statement parsers.

Each input picks a file suffix and an optional explicit format, writes
the remaining bytes to a statement file, and runs the public entry
point every caller uses: ``create_parser(path, format).parse()``,
which detects the format when none is given.

Malformed input has three documented outcomes: a
``BankStatementParserError`` (validation and parser failures), a
``ValueError`` (bad text encoding, a CSV row pandas cannot split, an
invalid XML name) or lxml's ``XMLSyntaxError`` for XML that does not
parse (``tests/integration/test_malformed_data.py`` asserts the last
two). Anything else escapes the target and libFuzzer records it as a
crash: a ``TypeError``, ``KeyError``, ``IndexError``,
``AttributeError``, ``RecursionError`` or arithmetic error means a
parser trusted its input.

Run (Linux x86_64, Python 3.12+, ``poetry install --with fuzz``)::

    python fuzz/fuzz_parsers.py -max_total_time=60
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import tempfile

import atheris

# Parsers log a warning or error for nearly every malformed input; at
# fuzzing speed that output would bury libFuzzer's own report.
logging.disable(logging.CRITICAL)

with atheris.instrument_imports():
    from lxml import etree

    from bankstatementparser import create_parser
    from bankstatementparser.exceptions import BankStatementParserError

_SUFFIXES = (
    ".xml",
    ".csv",
    ".ofx",
    ".qfx",
    ".mt940",
    ".sta",
    ".mt942",
    ".bai2",
    ".txt",
)
_FORMATS = (
    None,
    "camt",
    "camt052",
    "camt054",
    "pain001",
    "csv",
    "ofx",
    "qfx",
    "mt940",
    "mt942",
    "bai2",
)
_EXPECTED = (BankStatementParserError, ValueError, etree.XMLSyntaxError)
_WORKDIR = tempfile.mkdtemp(prefix="bsp-fuzz-")


def _pick(fdp: atheris.FuzzedDataProvider, choices: tuple) -> object:
    """Choose one element of ``choices`` from the fuzz input."""
    return choices[fdp.ConsumeIntInRange(0, len(choices) - 1)]


def test_one_input(data: bytes) -> None:
    """Parse one fuzz input as a statement file."""
    fdp = atheris.FuzzedDataProvider(data)
    suffix = _pick(fdp, _SUFFIXES)
    fmt = _pick(fdp, _FORMATS)
    path = os.path.join(_WORKDIR, f"statement{suffix}")
    with open(path, "wb") as handle:
        handle.write(fdp.ConsumeBytes(fdp.remaining_bytes()))
    # The documented refusals of bad input are not findings; anything
    # else escapes and is a crash.
    with contextlib.suppress(*_EXPECTED):
        create_parser(path, fmt).parse()


def main() -> None:
    """Hand the target to libFuzzer with the command-line options."""
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
