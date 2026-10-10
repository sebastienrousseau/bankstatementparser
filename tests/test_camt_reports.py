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

"""Tests for CAMT.052 and CAMT.054 streaming parser engines."""

from __future__ import annotations

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from bankstatementparser.additional_parsers import (
    create_parser,
    detect_statement_format,
)
from bankstatementparser.camt_reports import (
    Camt052Parser,
    Camt054Parser,
    _extract_entry_refs,
    _extract_parties,
    _parse_entry_records,
    _parse_iso_date,
    _strip_ns,
)
from bankstatementparser.exceptions import ParserError

SAMPLE_CAMT052 = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.02">
  <BkToCstmrAcctRpt>
    <Rpt>
      <Id>RPT-2026-001</Id>
      <CreDtTm>2026-03-31T12:00:00Z</CreDtTm>
      <Acct>
        <Id>
          <IBAN>GB33BUKB20201555555555</IBAN>
        </Id>
        <Ccy>GBP</Ccy>
      </Acct>
      <Bal>
        <Tp>
          <CdOrPrtry>
            <Cd>OPBD</Cd>
          </CdOrPrtry>
        </Tp>
        <Amt Ccy="GBP">1000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt><Dt>2026-03-31</Dt></Dt>
      </Bal>
      <Bal>
        <Tp>
          <CdOrPrtry>
            <Cd>CLBD</Cd>
          </CdOrPrtry>
        </Tp>
        <Amt Ccy="GBP">1400.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt><Dt>2026-03-31</Dt></Dt>
      </Bal>
      <Ntry>
        <Amt Ccy="GBP">500.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2026-03-31</Dt></BookgDt>
        <ValDt><Dt>2026-03-31</Dt></ValDt>
        <NtryDtls>
          <TxDtls>
            <Refs>
              <EndToEndId>E2E-001</EndToEndId>
            </Refs>
            <RltdPties>
              <Dbtr><Nm>Acme Corp</Nm></Dbtr>
              <Cdtr><Nm>Treasury Services</Nm></Cdtr>
            </RltdPties>
            <RmtInf>
              <Ustrd>Invoice 1001 payment</Ustrd>
            </RmtInf>
          </TxDtls>
        </NtryDtls>
      </Ntry>
      <Ntry>
        <Amt Ccy="GBP">100.00</Amt>
        <CdtDbtInd>DBIT</CdtDbtInd>
        <BookgDt><Dt>2026-03-31</Dt></BookgDt>
        <ValDt><Dt>2026-03-31</Dt></ValDt>
        <NtryDtls>
          <TxDtls>
            <Refs>
              <EndToEndId>E2E-002</EndToEndId>
            </Refs>
            <RltdPties>
              <Cdtr><Nm>Office Supplies Ltd</Nm></Cdtr>
            </RltdPties>
            <RmtInf>
              <Ustrd>Paper supplies</Ustrd>
            </RmtInf>
          </TxDtls>
        </NtryDtls>
      </Ntry>
    </Rpt>
  </BkToCstmrAcctRpt>
</Document>
"""

SAMPLE_CAMT054 = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.054.001.02">
  <BkToCstmrDbtCdtNtfctn>
    <Ntfctn>
      <Id>NTF-2026-999</Id>
      <CreDtTm>2026-04-01T08:30:00Z</CreDtTm>
      <Acct>
        <Id>
          <Othr>
            <Id>ACC-INTERNAL-42</Id>
          </Othr>
        </Id>
        <Ccy>EUR</Ccy>
      </Acct>
      <Ntry>
        <Amt Ccy="EUR">750.50</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><DtTm>2026-04-01T08:00:00Z</DtTm></BookgDt>
        <NtryDtls>
          <TxDtls>
            <Refs>
              <EndToEndId>NOTIF-E2E-77</EndToEndId>
            </Refs>
            <RltdPties>
              <Dbtr><Nm>Global Partner SA</Nm></Dbtr>
            </RltdPties>
            <RmtInf>
              <Ustrd>Settlement batch 44</Ustrd>
            </RmtInf>
          </TxDtls>
        </NtryDtls>
      </Ntry>
    </Ntfctn>
  </BkToCstmrDbtCdtNtfctn>
</Document>
"""


def _write_temp_file(content: str, suffix: str = ".xml") -> Path:
    """Write XML content to a temporary file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        return Path(f.name)


def test_camt_helpers() -> None:
    """Verify helper parsing functions for namespaces, dates, and elements."""
    assert _strip_ns("{urn:iso:std}Rpt") == "Rpt"
    assert _strip_ns("SimpleTag") == "SimpleTag"
    assert _parse_iso_date("2026-03-31T12:00:00Z") == date(2026, 3, 31)
    assert _parse_iso_date("2026-03-31") == date(2026, 3, 31)
    assert _parse_iso_date("") is None
    assert _parse_iso_date(None) is None
    assert _parse_iso_date("invalid-date-string") is None

    node = etree.fromstring(
        "<Ntry><RmtInf><Ustrd>Ref1</Ustrd></RmtInf><Refs><EndToEndId>E2E1</EndToEndId></Refs><RltdPties><Dbtr><Nm>Alice</Nm></Dbtr><Cdtr><Nm>Bob</Nm></Cdtr></RltdPties></Ntry>"
    )
    assert _extract_entry_refs(node) == ("Ref1", "E2E1")
    assert _extract_parties(node) == ("Alice", "Bob")


def test_camt052_parsing_and_summaries() -> None:
    """Verify end-to-end CAMT.052 statement report parsing."""
    file_path = _write_temp_file(SAMPLE_CAMT052)
    try:
        parser = Camt052Parser(file_path)
        df = parser.parse()
        assert len(df) == 2

        # Check transactions
        tx1 = df.iloc[0]
        assert tx1["AccountId"] == "GB33BUKB20201555555555"
        assert tx1["Currency"] == "GBP"
        assert tx1["Amount"] == Decimal("500.00")
        assert tx1["DrCr"] == "CRDT"
        assert tx1["Debtor"] == "Acme Corp"
        assert tx1["Creditor"] == "Treasury Services"
        assert tx1["EndToEndId"] == "E2E-001"
        assert tx1["Reference"] == "Invoice 1001 payment"

        tx2 = df.iloc[1]
        assert tx2["Amount"] == Decimal("-100.00")
        assert tx2["DrCr"] == "DBIT"

        # Check summary
        summary = parser.get_summary()
        assert summary["account_id"] == "GB33BUKB20201555555555"
        assert summary["currency"] == "GBP"
        assert summary["transaction_count"] == 2
        assert summary["total_amount"] == Decimal("400.00")
        assert summary["opening_balance"] == Decimal("1000.00")
        assert summary["closing_balance"] == Decimal("1400.00")

        # Check model generator
        models = list(parser.parse_streaming_transactions())
        assert len(models) == 2
        assert models[0].amount == Decimal("500.00")
        assert models[0].booking_date == date(2026, 3, 31)
    finally:
        file_path.unlink(missing_ok=True)


def test_camt054_parsing_and_streaming() -> None:
    """Verify CAMT.054 debit/credit notification parsing and factory detection."""
    file_path = _write_temp_file(SAMPLE_CAMT054)
    try:
        assert detect_statement_format(file_path) == "camt054"
        parser = create_parser(file_path)
        assert isinstance(parser, Camt054Parser)

        stream = list(parser.parse_streaming())
        assert len(stream) == 1
        assert stream[0]["AccountId"] == "ACC-INTERNAL-42"
        assert stream[0]["Currency"] == "EUR"
        assert stream[0]["Amount"] == Decimal("750.50")
        assert stream[0]["EndToEndId"] == "NOTIF-E2E-77"
        assert stream[0]["Reference"] == "Settlement batch 44"

        # Cached parse
        df = parser.parse()
        assert parser.parse() is df

        summary = parser.get_summary()
        assert summary["account_id"] == "ACC-INTERNAL-42"
        assert summary["currency"] == "EUR"
        assert summary["transaction_count"] == 1
        assert summary["total_amount"] == Decimal("750.50")
        assert summary["opening_balance"] is None
        assert summary["closing_balance"] is None
    finally:
        file_path.unlink(missing_ok=True)


def test_camt_from_string_and_bytes() -> None:
    """Verify classmethods from_string and from_bytes."""
    p_str = Camt054Parser.from_string(SAMPLE_CAMT054)
    df_str = p_str.parse()
    assert len(df_str) == 1

    p_bytes = Camt052Parser.from_bytes(SAMPLE_CAMT052.encode("utf-8"))
    df_bytes = p_bytes.parse()
    assert len(df_bytes) == 2


def test_camt_multi_scope_and_empty() -> None:
    """Verify multi-scope report handling and empty documents."""
    multi_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.02">
  <BkToCstmrAcctRpt>
    <Rpt><Acct><Id><IBAN>ACC1</IBAN></Id></Acct></Rpt>
    <Rpt><Acct><Id><IBAN>ACC2</IBAN></Id></Acct></Rpt>
  </BkToCstmrAcctRpt>
</Document>"""
    p_multi = Camt052Parser.from_string(multi_xml)
    summaries = p_multi.get_summaries()
    assert len(summaries) == 2
    with pytest.raises(ValueError, match="Multiple summary scopes"):
        p_multi.get_summary()

    empty_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.02">
  <BkToCstmrAcctRpt></BkToCstmrAcctRpt>
</Document>"""
    p_empty = Camt052Parser.from_string(empty_xml)
    df_empty = p_empty.parse()
    assert df_empty.empty
    summary_empty = p_empty.get_summary()
    assert summary_empty["account_id"] is None
    assert summary_empty["transaction_count"] == 0


def test_camt_parsing_error_branches() -> None:
    """Verify edge case errors for missing mandatory elements in entries."""
    # Missing Amt
    elem_missing_amt = etree.fromstring(
        "<Ntry><CdtDbtInd>CRDT</CdtDbtInd></Ntry>"
    )
    with pytest.raises(ValueError, match="missing <Amt>"):
        _parse_entry_records(elem_missing_amt, "ACC", "EUR", False)

    # Missing CdtDbtInd
    elem_missing_drcr = etree.fromstring(
        '<Ntry><Amt Ccy="EUR">100</Amt></Ntry>'
    )
    with pytest.raises(ParserError, match="missing <CdtDbtInd>"):
        _parse_entry_records(elem_missing_drcr, "ACC", "EUR", False)

    # Missing currency
    elem_missing_ccy = etree.fromstring(
        "<Ntry><Amt>100</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry>"
    )
    with pytest.raises(ParserError, match="missing currency"):
        _parse_entry_records(elem_missing_ccy, "ACC", "", False)

    # Invalid direction
    elem_invalid_drcr = etree.fromstring(
        '<Ntry><Amt Ccy="EUR">100</Amt><CdtDbtInd>UNKNOWN</CdtDbtInd></Ntry>'
    )
    with pytest.raises(ParserError, match="Invalid CdtDbtInd"):
        _parse_entry_records(elem_invalid_drcr, "ACC", "EUR", False)

    # Short date string (< 10 chars)
    assert _parse_iso_date("2026") is None

    # Redact PII in parse
    p_redacted = Camt054Parser.from_string(SAMPLE_CAMT054)
    df_red = p_redacted.parse(redact_pii=True)
    assert len(df_red) == 1

    # Balance handling edge cases
    bal_empty_amt = etree.fromstring(
        "<Bal><Amt></Amt><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp></Bal>"
    )
    dummy_summary = {"opening_balance": None, "closing_balance": None}
    p_redacted._handle_balance_tag(bal_empty_amt, None)
    p_redacted._handle_balance_tag(bal_empty_amt, dummy_summary)
    assert dummy_summary["opening_balance"] is None

    bal_other_code = etree.fromstring(
        "<Bal><Amt>50</Amt><Tp><CdOrPrtry><Cd>OTHER</Cd></CdOrPrtry></Tp></Bal>"
    )
    p_redacted._handle_balance_tag(bal_other_code, dummy_summary)
    assert dummy_summary["opening_balance"] is None

    # Top-level entries outside a scope
    orphan_xml = """<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.02">
      <Acct><Id><IBAN>ORPHAN</IBAN></Id></Acct>
      <CreDtTm>2026-03-31T10:00:00Z</CreDtTm>
      <Ntry><Amt Ccy="EUR">10</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry>
    </Document>"""
    p_orphan = Camt052Parser.from_string(orphan_xml)
    assert len(list(p_orphan.parse_streaming())) == 1
