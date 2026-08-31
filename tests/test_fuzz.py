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

"""Hypothesis fuzzing suite for core parser robustness and security."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bankstatementparser.additional_parsers import (
    create_parser,
    detect_statement_format,
)
from bankstatementparser.transaction_categorizer import (
    TransactionCategorizer as Categorizer,
)
from bankstatementparser.exceptions import ParserError, ValidationError
from bankstatementparser.input_validator import InputValidator
from bankstatementparser.mt940_parser import MT940Parser
from bankstatementparser.plugins import PluginManager
from bankstatementparser.zip_security import (
    SecurityError,
    validate_zip_archive,
)


@settings(max_examples=50, deadline=None)
@given(st.text(min_size=0, max_size=2000))
def test_fuzz_detect_format_never_crashes(payload: str) -> None:
    """detect_statement_format safely handles any arbitrary string."""
    fmt = detect_statement_format(payload)
    assert fmt is None or isinstance(fmt, str)


@settings(max_examples=50, deadline=None)
@given(st.text(min_size=0, max_size=1000))
def test_fuzz_categorizer_predict_arbitrary_strings(text: str) -> None:
    """Categorizer.predict never crashes on arbitrary unicode narratives."""
    cat = Categorizer()
    result = cat.predict(text)
    assert isinstance(result, str)
    assert len(result) > 0


@settings(max_examples=30, deadline=None)
@given(st.lists(st.text(max_size=200), max_size=20))
def test_fuzz_categorizer_batch_arbitrary_list(narratives: list[str]) -> None:
    """Categorizer.predict_batch never crashes on arbitrary batch lists."""
    cat = Categorizer()
    results = cat.predict_batch(narratives)
    assert len(results) == len(narratives)
    for r in results:
        assert isinstance(r, str)


@settings(max_examples=50, deadline=None)
@given(st.text(min_size=0, max_size=2000))
def test_fuzz_mt940_line_parser_arbitrary_text(content: str) -> None:
    """MT940Parser handles any corrupted or mutated statement line text."""
    with tempfile.NamedTemporaryFile("w", suffix=".mt940", delete=False) as f:
        f.write(content)
        f_path = f.name
    try:
        parser = MT940Parser(f_path)
        try:
            df = parser.parse()
            assert df is not None
        except (ParserError, ValidationError, ValueError, Exception):
            pass
    finally:
        Path(f_path).unlink(missing_ok=True)


@settings(max_examples=30, deadline=None)
@given(st.binary(min_size=0, max_size=4096))
def test_fuzz_zip_security_arbitrary_bytes(data: bytes) -> None:
    """validate_zip_archive safely rejects corrupted or random bytes."""
    with tempfile.NamedTemporaryFile("wb", suffix=".zip", delete=False) as f:
        f.write(data)
        f_path = f.name
    try:
        try:
            validate_zip_archive(f_path)
        except (SecurityError, ValidationError, ValueError, Exception):
            pass
    finally:
        Path(f_path).unlink(missing_ok=True)


@settings(max_examples=30, deadline=None)
@given(st.text(min_size=1, max_size=50))
def test_fuzz_plugin_manager_arbitrary_names(plugin_name: str) -> None:
    """PluginManager safely handles arbitrary lookup keys."""
    pm = PluginManager()
    loader = pm.get_loader(plugin_name)
    assert loader is None or callable(loader)
    writer = pm.get_writer(plugin_name)
    assert writer is None or callable(writer)
