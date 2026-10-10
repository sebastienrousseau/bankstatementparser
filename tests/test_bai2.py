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

"""Tests for BAI2 statement parser."""

from __future__ import annotations

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bankstatementparser.additional_parsers import (
    create_parser,
    detect_statement_format,
)
from bankstatementparser.exceptions import ValidationError
from bankstatementparser.parsers.bai2 import (
    Bai2Parser,
    _parse_bai2_amount,
    _parse_bai2_date,
)


def _write_temp_file(content: str, suffix: str = ".bai2") -> Path:
    """Write content to a temporary file and return Path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        return Path(f.name)


def test_parse_bai2_date_helpers() -> None:
    """Verify BAI2 date parsing for different formats and invalid input."""
    assert _parse_bai2_date("250115") == date(2025, 1, 15)
    assert _parse_bai2_date("20250115") == date(2025, 1, 15)
    assert _parse_bai2_date("") is None
    assert _parse_bai2_date("   ") is None
    assert _parse_bai2_date("invalid_date") is None


def test_parse_bai2_amount_helpers() -> None:
    """Verify BAI2 amount parsing for cents, explicit decimals, and empty."""
    assert _parse_bai2_amount("50000", "USD") == Decimal("500.00")
    assert _parse_bai2_amount("123.45", "EUR") == Decimal("123.45")
    assert _parse_bai2_amount("", "USD") == Decimal("0.00")
    assert _parse_bai2_amount("  ", "USD") == Decimal("0.00")


def test_bai2_standard_parsing() -> None:
    """Verify full end-to-end parsing of a standard BAI2 statement."""
    content = """01,CITI,CORP,250115,1000,1,80,2/
02,CORP,CITI,1,250115,1000,USD/
03,987654321,USD,010,1000000,,,015,1250000,,,/
16,175,50000,Z,BNK001,CUST001,Customer Deposit/
16,475,25000,Z,BNK002,CUST002,Supplier Wire/
16,999,10000,Z,BNK003,CUST003,Administrative Adjustment/
49,1250000,5/
98,1250000,1,7/
99,1250000,1,9/
"""
    file_path = _write_temp_file(content, suffix=".bai2")
    try:
        parser = Bai2Parser(file_path)
        df = parser.parse()
        assert len(df) == 3

        # Transaction 1: Credit (175)
        tx1 = df.iloc[0]
        assert tx1["AccountId"] == "987654321"
        assert tx1["Currency"] == "USD"
        assert tx1["Amount"] == Decimal("500.00")
        assert tx1["description"] == "Customer Deposit"
        assert tx1["Reference"] == "CUST001"
        assert tx1["transaction_id"] == "BNK001"
        assert tx1["BookgDt"] == "2025-01-15"

        # Transaction 2: Debit (475)
        tx2 = df.iloc[1]
        assert tx2["Amount"] == Decimal("-250.00")
        assert tx2["description"] == "Supplier Wire"

        # Transaction 3: Other code (999 -> non-debit)
        tx3 = df.iloc[2]
        assert tx3["Amount"] == Decimal("100.00")

        # Summary check
        summary = parser.get_summary()
        assert summary["account_id"] == "987654321"
        assert summary["currency"] == "USD"
        assert summary["transaction_count"] == 3
        assert summary["total_amount"] == 350.0
        assert summary["opening_balance"] == 10000.0
        assert summary["closing_balance"] == 12500.0

        # Repeated parse returns cached df
        assert parser.parse() is df
    finally:
        file_path.unlink(missing_ok=True)


def test_bai2_streaming() -> None:
    """Verify parse_streaming yields transaction dictionaries."""
    content = """01,BANK,CLIENT,250115,1000,1,80,2/
02,CLIENT,BANK,1,250115,1000,EUR/
03,ACCT100,EUR,040,50000,,,045,70000,,,/
16,108,20000,Z,,,Generic Credit/
49,70000,3/
98,70000,1,5/
99,70000,1,7/
"""
    file_path = _write_temp_file(content, suffix=".bai")
    try:
        parser = Bai2Parser(file_path)
        items = list(parser.parse_streaming())
        assert len(items) == 1
        assert items[0]["AccountId"] == "ACCT100"
        assert items[0]["Currency"] == "EUR"
        assert items[0]["Amount"] == Decimal("200.00")
        assert items[0]["description"] == "Generic Credit"
        assert items[0]["Reference"] is None
    finally:
        file_path.unlink(missing_ok=True)


def test_bai2_multi_account_summaries() -> None:
    """Verify multi-account statements produce scoped summaries."""
    content = """01,SENDER,RECEIVER,250115,1000,1,80,2/
02,RECEIVER,SENDER,1,250115,1000,USD/
03,ACC1,USD/
16,175,10000,Z,,,Tx1/
03,ACC2,USD/
16,175,20000,Z,,,Tx2/
99,30000,1,6/
"""
    file_path = _write_temp_file(content, suffix=".bai2")
    try:
        parser = Bai2Parser(file_path)
        df = parser.parse()
        assert len(df) == 2

        summaries = parser.get_summaries()
        assert len(summaries) == 2
        assert summaries[0]["account_id"] == "ACC1"
        assert summaries[1]["account_id"] == "ACC2"

        # get_summary raises ValueError on multiple summaries
        with pytest.raises(
            ValueError, match="Multiple summary scopes; use get_summaries"
        ):
            parser.get_summary()
    finally:
        file_path.unlink(missing_ok=True)


def test_bai2_empty_file() -> None:
    """Verify empty BAI2 file validation and whitespace-only handling."""
    zero_byte = _write_temp_file("", suffix=".bai2")
    try:
        with pytest.raises(ValidationError):
            Bai2Parser(zero_byte)
    finally:
        zero_byte.unlink(missing_ok=True)

    file_path = _write_temp_file("\n\n", suffix=".bai2")
    try:
        parser = Bai2Parser(file_path)
        df = parser.parse()
        assert df.empty
        assert "AccountId" in df.columns

        summary = parser.get_summary()
        assert summary["account_id"] is None
        assert summary["transaction_count"] == 0
    finally:
        file_path.unlink(missing_ok=True)


def test_bai2_format_detection_and_create_parser() -> None:
    """Verify auto-detection by extension and header content."""
    bai2_content = "01,SENDER,RECEIVER,250115,1000,1,80,2/\n99,0,0,2/"
    path_suffix = _write_temp_file(bai2_content, suffix=".bai2")
    path_bai = _write_temp_file(bai2_content, suffix=".bai")

    try:
        assert detect_statement_format(path_suffix) == "bai2"
        assert detect_statement_format(path_bai) == "bai2"

        p1 = create_parser(path_suffix)
        assert isinstance(p1, Bai2Parser)

        p2 = create_parser(path_bai, format_name="bai2")
        assert isinstance(p2, Bai2Parser)
    finally:
        path_suffix.unlink(missing_ok=True)
        path_bai.unlink(missing_ok=True)


def test_bai2_edge_cases() -> None:
    """Verify edge cases such as malformed records and default descriptions."""
    content = """01/
02,RECV,ORIG,1,invalid_date,1000/
16,108,2000,Z,EARLY
88,CONT_DATA/
03,ACC_ONLY/
16/
16,non_numeric,5000/
16,108,1000,Z,BNK_ONLY/
49,1000,1/
"""
    file_path = _write_temp_file(content, suffix=".bai2")
    try:
        parser = Bai2Parser(file_path)
        df = parser.parse()
        # EARLY parsed without prior 03 and without trailing slash
        # 16/ was skipped (len < 3)
        # 16,non_numeric,5000 parsed (default desc: Type non_numeric)
        # 16,108,1000,Z,BNK_ONLY parsed (default desc: Type 108, ref: BNK_ONLY)
        assert len(df) == 3
        assert df.iloc[0]["Reference"] == "EARLY"
        assert df.iloc[1]["description"] == "Type non_numeric"
        assert df.iloc[2]["Reference"] == "BNK_ONLY"
    finally:
        file_path.unlink(missing_ok=True)


def test_bai2_direct_summary() -> None:
    """Verify get_summary and get_summaries trigger parse if unparsed."""
    content = "01,A,B/\n02/\n03,ACC1,USD,999,1000/\n16,100,500,Z,,CUST_ONLY/\n49,500,1/\n"
    file_path = _write_temp_file(content, suffix=".bai2")
    try:
        p1 = Bai2Parser(file_path)
        summary = p1.get_summary()
        assert summary["account_id"] == "ACC1"

        p2 = Bai2Parser(file_path)
        summaries = p2.get_summaries()
        assert len(summaries) == 1
    finally:
        file_path.unlink(missing_ok=True)
