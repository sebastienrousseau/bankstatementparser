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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for v0.0.19 features: plugin registry, MT940 reversals, multi-format zip security."""

from decimal import Decimal
from pathlib import Path
import tempfile
import zipfile
import pandas as pd
import pytest

from bankstatementparser import (
    BankStatementParser,
    Mt940Parser,
    create_parser,
    detect_statement_format,
    discover_loaders,
    discover_writers,
    iter_secure_statement_entries,
    register_loader,
    register_writer,
)
from bankstatementparser.plugins import unregister_loader, unregister_writer
from bankstatementparser.record_types import SummaryRecord


class DummyCustomParser(BankStatementParser):
    """Dummy custom parser for plugin testing."""

    def parse(self) -> pd.DataFrame:
        return pd.DataFrame([{"date": "2026-08-31", "amount": Decimal("100.00")}])

    def get_summary(self) -> SummaryRecord:
        return {
            "account_id": "DUMMY",
            "statement_date": "2026-08-31",
            "transaction_count": 1,
            "total_amount": Decimal("100.00"),
            "opening_balance": None,
            "closing_balance": None,
            "currency": "EUR",
        }


def test_plugin_registration_and_creation(tmp_path: Path) -> None:
    register_loader("customfmt", DummyCustomParser)
    test_file = tmp_path / "test.customfmt"
    test_file.write_text("dummy content", encoding="utf-8")

    assert detect_statement_format(test_file) == "customfmt"
    parser = create_parser(test_file, "customfmt")
    assert isinstance(parser, DummyCustomParser)
    df = parser.parse()
    assert len(df) == 1

    unregister_loader("customfmt")


def test_writer_registration() -> None:
    def dummy_writer(data, path, **kwargs):
        return Path(path)

    register_writer("dummy_xlsx", dummy_writer)
    writers = discover_writers()
    # Manual registration is tracked in get_registered_writers
    from bankstatementparser.plugins import get_registered_writers
    assert "dummy_xlsx" in get_registered_writers()
    unregister_writer("dummy_xlsx")


def test_mt940_reversals_and_multiline_86(tmp_path: Path) -> None:
    mt940_content = """
:20:START
:25:NL12BANK1234567890
:60F:C260101EUR1000,00
:61:2601020102RC150,00NTRFNONREF//12345
:86:Reversal of erroneous debit
 continuation line 1
 continuation line 2
:61:2601030103RD50,00NTRFNONREF//12346
:86:Reversal of erroneous credit
:62F:C260104EUR1100,00
-
"""
    file_path = tmp_path / "statement.mt940"
    file_path.write_text(mt940_content.strip(), encoding="utf-8")

    parser = Mt940Parser(file_path)
    df = parser.parse()
    assert len(df) == 2

    # RC (reversal of credit/debit -> credit = positive)
    assert df.iloc[0]["amount"] == Decimal("150.00")
    assert "continuation line 1" in str(df.iloc[0]["description"])
    assert "continuation line 2" in str(df.iloc[0]["description"])

    # RD (reversal debit = negative)
    assert df.iloc[1]["amount"] == Decimal("-50.00")


def test_zip_security_multi_format(tmp_path: Path) -> None:
    zip_file = tmp_path / "statements.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("test.csv", "date,amount\n2026-08-31,50.00")
        zf.writestr("test.mt940", ":20:1\n:25:A\n:60F:C260101EUR100,00\n:62F:C260102EUR100,00")

    entries = list(iter_secure_statement_entries(zip_file))
    assert len(entries) == 2
    names = [e.source_name for e in entries]
    assert "test.csv" in names
    assert "test.mt940" in names
