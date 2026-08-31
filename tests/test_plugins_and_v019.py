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

"""Tests for v0.0.19 features: plugin registry, MT940 reversals, CAMT.053 batches, multi-format zip security."""

import json
import zipfile
from decimal import Decimal
from pathlib import Path
from zipfile import ZipInfo

import pandas as pd
import pytest

from bankstatementparser import (
    BankStatementParser,
    CamtParser,
    Mt940Parser,
    create_parser,
    detect_statement_format,
    discover_loaders,
    discover_writers,
    iter_secure_statement_entries,
    register_loader,
    register_writer,
)
from bankstatementparser.enrichment.categorizer import (
    ENV_ENRICHMENT_MODEL,
    ENV_FALLBACK_MODEL,
    Categorizer,
    _format_row,
)
from bankstatementparser.input_validator import ValidationError
from bankstatementparser.plugins import (
    get_registered_loaders,
    get_registered_writers,
    unregister_loader,
    unregister_writer,
)
from bankstatementparser.record_types import SummaryRecord
from bankstatementparser.transaction_models import Transaction
from bankstatementparser.zip_security import (
    ZipSecurityError,
    _validate_zip_member,
)


class DummyCustomParser(BankStatementParser):
    """Dummy custom parser for plugin testing."""

    def __init__(self, file_name: str | Path) -> None:
        super().__init__(file_name)
        self._text = Path(file_name).read_text(encoding="utf-8")

    def parse(self) -> pd.DataFrame:
        return pd.DataFrame(
            [{"date": "2026-08-31", "amount": Decimal("100.00")}]
        )

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
    summary = parser.get_summary()
    assert summary["account_id"] == "DUMMY"

    # Unsupported format error
    with pytest.raises(ValidationError, match="Unsupported statement format"):
        create_parser(test_file, "nonexistent_format_xyz")

    # Unmatched plugin in detect_statement_format (valid extension, unknown format)
    bad_fmt_file = tmp_path / "unknown_content.xml"
    bad_fmt_file.write_text(
        "unknown content without any known tags", encoding="utf-8"
    )
    with pytest.raises(
        ValidationError, match="Unable to detect statement format"
    ):
        detect_statement_format(bad_fmt_file)

    unregister_loader("customfmt")
    unregister_loader("nonexistent_loader")
    assert "customfmt" not in get_registered_loaders()


def test_writer_registration_and_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def dummy_writer(data, path, **kwargs):
        return Path(path)

    register_writer("dummy_xlsx", dummy_writer)
    assert "dummy_xlsx" in get_registered_writers()
    unregister_writer("dummy_xlsx")
    unregister_writer("nonexistent_writer")
    assert "dummy_xlsx" not in get_registered_writers()

    # Test error handling when entry point load fails and succeeds
    class FailingEP:
        name = "bad_loader"

        def load(self):
            raise RuntimeError("simulated error")

    class WorkingEP:
        name = "good_loader"

        def load(self):
            return DummyCustomParser

    class FakeEPs:
        def select(self, group=None):
            return [FailingEP(), WorkingEP()]

        def get(self, group, default=None):
            return [FailingEP(), WorkingEP()]

    monkeypatch.setattr("importlib.metadata.entry_points", lambda: FakeEPs())
    discovered_l = discover_loaders()
    assert "bad_loader" not in discovered_l
    assert "good_loader" in discovered_l

    discovered_w = discover_writers()
    assert "bad_loader" not in discovered_w
    assert "good_loader" in discovered_w

    # Test when entry_points raises completely
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda: (_ for _ in ()).throw(RuntimeError("EP lookup failed")),
    )
    assert discover_loaders() == {}
    assert discover_writers() == {}


def test_mt940_reversals_and_multiline_86(tmp_path: Path) -> None:
    mt940_content = """
:20:START
:25:NL12BANK1234567890

:60F:C260101EUR1000,00
:60M:C260101EUR1000,00
:61:2601020102RC150,00NTRFNONREF//12345
:86:Reversal of erroneous debit
 continuation line 1
 continuation line 2
:25:NL12BANK1234567891
:61:2601030103RD50,00NTRFNONREF//12346
:86:Reversal of erroneous credit
:61:2601030103EC200,00NTRFNONREF//12347
:86:Electronic credit
:61:2601030103ED75,00NTRFNONREF//12348
:86:Electronic debit
-Narrative end
:62M:C260104EUR1275,00
:62F:C260104EUR1275,00

"""
    file_path = tmp_path / "statement.mt940"
    file_path.write_text(mt940_content.strip(), encoding="utf-8")

    parser = Mt940Parser(file_path)
    df = parser.parse()
    assert len(df) == 4

    # RC (reversal of credit/debit -> credit = positive)
    assert df.iloc[0]["amount"] == Decimal("150.00")
    assert "continuation line 1" in str(df.iloc[0]["description"])
    assert "continuation line 2" in str(df.iloc[0]["description"])

    # RD (reversal debit = negative)
    assert df.iloc[1]["amount"] == Decimal("-50.00")

    # EC (electronic credit = positive)
    assert df.iloc[2]["amount"] == Decimal("200.00")

    # ED (electronic debit = negative)
    assert df.iloc[3]["amount"] == Decimal("-75.00")

    summary = parser.get_summary()
    assert summary["transaction_count"] == 4
    assert summary["opening_balance"] == Decimal("1000.00")
    assert summary["closing_balance"] == Decimal("1275.00")


def test_detect_format_all_types(tmp_path: Path) -> None:
    bai2_file = tmp_path / "sample.bai2"
    bai2_file.write_text(
        "01,SENDER,RECEIVER,260101,1200,1/\n02,GROUP/\n99,TRAILER/",
        encoding="utf-8",
    )
    assert detect_statement_format(bai2_file) == "bai2"

    mt942_file = tmp_path / "sample.mt942"
    mt942_file.write_text(
        ":20:REPORT\n:25:ACCT123\n:34F:EUR2601010,00\n:61:260101C100,00NTRF\n:86:DETAILS\n-",
        encoding="utf-8",
    )
    assert detect_statement_format(mt942_file) == "mt942"

    csv_file = tmp_path / "sample.csv"
    csv_file.write_text(
        "Date,Amount,Description\n2026-01-01,10.00,Test\n",
        encoding="utf-8",
    )
    assert detect_statement_format(csv_file) == "csv"

    ofx_file = tmp_path / "sample.ofx"
    ofx_file.write_text(
        "<OFX><BANKTRANLIST></BANKTRANLIST></OFX>", encoding="utf-8"
    )
    assert detect_statement_format(ofx_file) == "ofx"

    sta_file = tmp_path / "sample.sta"
    sta_file.write_text(
        ":20:STA\n:25:123\n:60F:C260101EUR0,00\n:61:260101C10,00NTRF\n:62F:C260102EUR10,00\n",
        encoding="utf-8",
    )
    assert detect_statement_format(sta_file) == "mt940"


def test_camt_extract_transactions_batch_and_redact(
    tmp_path: Path,
) -> None:
    camt_content = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Id>STMT001</Id>
      <Acct><Id><IBAN>DE89370400440532013000</IBAN></Id></Acct>
      <Ntry>
        <Amt Ccy="EUR">300.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <ValDt><Dt>2026-01-01</Dt></ValDt>
        <BookgDt><Dt>2026-01-01</Dt></BookgDt>
        <NtryDtls>
          <TxDtls>
            <Amt Ccy="EUR">100.00</Amt>
            <CdtDbtInd>CRDT</CdtDbtInd>
            <RltdPties>
              <Dbtr><Nm>John Doe</Nm><PstlAdr><AdrLine>123 Street</AdrLine></PstlAdr></Dbtr>
              <Cdtr><Nm>Jane Smith</Nm><PstlAdr><AdrLine>456 Avenue</AdrLine></PstlAdr></Cdtr>
            </RltdPties>
            <RmtInf><Ustrd>Sub-invoice 1</Ustrd><Strd><CdtrRefInf><Ref>RF1812345</Ref></CdtrRefInf></Strd></RmtInf>
          </TxDtls>
          <TxDtls>
            <Amt Ccy="EUR">200.00</Amt>
            <CdtDbtInd>DBIT</CdtDbtInd>
            <RltdPties>
              <Dbtr><Nm>John Doe</Nm></Dbtr>
            </RltdPties>
            <RmtInf><Ustrd>Sub-invoice 2</Ustrd></RmtInf>
          </TxDtls>
        </NtryDtls>
      </Ntry>
      <Ntry>
        <Amt Ccy="EUR">50.00</Amt>
        <CdtDbtInd>DBIT</CdtDbtInd>
        <ValDt><Dt>2026-01-02</Dt></ValDt>
        <BookgDt><Dt>2026-01-02</Dt></BookgDt>
        <Dbtr><Nm>Company A</Nm><PstlAdr><AdrLine>HQ Road</AdrLine></PstlAdr></Dbtr>
        <Cdtr><Nm>Vendor B</Nm><PstlAdr><AdrLine>Vendor Lane</AdrLine></PstlAdr></Cdtr>
        <RmtInf><Ustrd>Single entry payment</Ustrd></RmtInf>
      </Ntry>
      <Ntry>
        <Amt Ccy="EUR">25.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <ValDt><Dt>2026-01-03</Dt></ValDt>
        <BookgDt><Dt>2026-01-03</Dt></BookgDt>
        <Dbtr><Nm>Company A</Nm></Dbtr>
        <Cdtr><Nm>Vendor B</Nm></Cdtr>
        <RmtInf><Ustrd>No address entry</Ustrd></RmtInf>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>
"""
    file_path = tmp_path / "batch_camt.xml"
    file_path.write_text(camt_content, encoding="utf-8")

    # 1. Parse normally
    parser = CamtParser(file_path)
    df = parser.parse()
    assert len(df) == 4

    # Check first batch item
    assert df.iloc[0]["Amount"] == Decimal("100.00")
    assert "RF1812345" in df.iloc[0]["Reference"]
    assert df.iloc[0]["DebtorAddress"] == "123 Street"

    # Check second batch item (debit -> negative)
    assert df.iloc[1]["Amount"] == Decimal("-200.00")

    # Check single entry item
    assert df.iloc[2]["Amount"] == Decimal("-50.00")
    assert df.iloc[2]["DebtorAddress"] == "HQ Road"

    # 2. Parse with PII redaction
    parser_pii = CamtParser(file_path)
    df_pii = parser_pii.parse(redact_pii=True)
    assert df_pii.iloc[0]["DebtorAddress"] == "***REDACTED***"
    assert df_pii.iloc[0]["CreditorAddress"] == "***REDACTED***"
    assert df_pii.iloc[2]["DebtorAddress"] == "***REDACTED***"
    assert df_pii.iloc[2]["CreditorAddress"] == "***REDACTED***"
    assert (
        pd.isna(df_pii.iloc[3]["DebtorAddress"])
        or df_pii.iloc[3]["DebtorAddress"] == ""
    )


def test_categorizer_concurrency_and_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tx_no_ccy = Transaction(
        date="2026-01-01", amount=Decimal("10.00"), description="Test"
    )
    row_str = _format_row(0, tx_no_ccy)
    assert "10.00" in row_str

    # Test fallback model environment variables
    monkeypatch.setenv(ENV_ENRICHMENT_MODEL, "openai/gpt-4o-mini")
    cat_env = Categorizer()
    assert cat_env._resolved_model == "openai/gpt-4o-mini"
    monkeypatch.delenv(ENV_ENRICHMENT_MODEL, raising=False)

    monkeypatch.setenv(ENV_FALLBACK_MODEL, "openai/gpt-4o")
    cat_env2 = Categorizer()
    assert cat_env2._resolved_model == "openai/gpt-4o"
    monkeypatch.delenv(ENV_FALLBACK_MODEL, raising=False)

    txs = [
        Transaction(
            date="2026-01-01",
            amount=Decimal("10.00"),
            description=f"Transaction {i}",
            currency="EUR",
        )
        for i in range(6)
    ]

    def mock_completion(**kwargs):
        messages = kwargs.get("messages", [])
        rows = [
            line
            for line in messages[1]["content"].splitlines()
            if line.strip().startswith("[")
        ]
        items = [
            {
                "index": i,
                "category": "Groceries",
                "confidence": 0.95,
                "rationale": "ok",
            }
            for i in range(len(rows))
        ]
        return {
            "choices": [
                {"message": {"content": json.dumps({"results": items})}}
            ]
        }

    categorizer = Categorizer(
        schema=("Groceries",),
        batch_size=2,
        max_concurrency=3,
        completion_fn=mock_completion,
    )
    results = categorizer.categorize_batch(txs)
    assert len(results) == 6
    assert all(r.category == "Groceries" for r in results)

    # Invalid configuration validation
    with pytest.raises(ValueError, match="schema must be a non-empty tuple"):
        Categorizer(schema=())
    with pytest.raises(ValueError, match="batch_size must be at least 1"):
        Categorizer(batch_size=0)
    with pytest.raises(ValueError, match="max_concurrency must be at least 1"):
        Categorizer(max_concurrency=0)

    # Test error handling when chunk fails
    def failing_completion(**kwargs):
        raise RuntimeError("LLM API timeout")

    failing_cat = Categorizer(
        batch_size=5,
        max_concurrency=2,
        completion_fn=failing_completion,
    )
    fallback_res = failing_cat.categorize_batch(txs)
    assert len(fallback_res) == 6
    assert all(r.category is None for r in fallback_res)
    assert "categorization failed" in fallback_res[0].rationale


def test_zip_security_multi_format_and_errors(tmp_path: Path) -> None:
    zip_file = tmp_path / "statements.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("folder/", "")
        zf.writestr("ignored.txt", "ignore me")
        zf.writestr("test.csv", "date,amount\n2026-08-31,50.00")
        zf.writestr(
            "test.mt940",
            ":20:1\n:25:A\n:60F:C260101EUR100,00\n:62F:C260102EUR100,00",
        )

    entries = list(iter_secure_statement_entries(zip_file))
    assert len(entries) == 2
    names = [e.source_name for e in entries]
    assert "test.csv" in names
    assert "test.mt940" in names

    # Test invalid zip archive path
    invalid_zip = tmp_path / "corrupt.zip"
    invalid_zip.write_bytes(b"not a real zip")
    with pytest.raises(ZipSecurityError, match="Invalid ZIP archive"):
        list(iter_secure_statement_entries(invalid_zip))

    # Test invalid parameter validation
    with pytest.raises(ZipSecurityError, match="max_entry_size"):
        list(iter_secure_statement_entries(zip_file, max_entry_size=0))
    with pytest.raises(ZipSecurityError, match="max_total_uncompressed_size"):
        list(
            iter_secure_statement_entries(
                zip_file, max_total_uncompressed_size=0
            )
        )
    with pytest.raises(ZipSecurityError, match="max_compression_ratio"):
        list(iter_secure_statement_entries(zip_file, max_compression_ratio=0))

    # Test empty zip
    empty_zip = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty_zip, "w"):
        pass
    with pytest.raises(ZipSecurityError, match="does not contain any entries"):
        list(iter_secure_statement_entries(empty_zip))

    # Test uncompressed size exceeding limit
    with pytest.raises(
        ZipSecurityError,
        match="exceeds the total allowed uncompressed size",
    ):
        list(
            iter_secure_statement_entries(
                zip_file, max_total_uncompressed_size=10
            )
        )

    # Test member validation unit helper
    zinfo = ZipInfo("bad.xml")
    zinfo.file_size = 0
    with pytest.raises(ZipSecurityError, match="empty or invalid"):
        _validate_zip_member(
            zinfo, max_entry_size=100, max_compression_ratio=10
        )

    zinfo.file_size = 500
    with pytest.raises(
        ZipSecurityError,
        match="exceeds the allowed uncompressed size limit",
    ):
        _validate_zip_member(
            zinfo, max_entry_size=100, max_compression_ratio=10
        )

    zinfo.file_size = 50
    zinfo.compress_size = 0
    with pytest.raises(ZipSecurityError, match="invalid compressed size"):
        _validate_zip_member(
            zinfo, max_entry_size=100, max_compression_ratio=10
        )
