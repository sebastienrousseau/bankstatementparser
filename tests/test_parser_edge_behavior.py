# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Parser behavior on sparse and unusual-but-valid input.

Real bank files frequently omit optional ISO 20022 elements (GrpHdr,
balances, debtor names) or carry vendor extensions the parsers do not
recognize. These tests pin the contract for those shapes: parsing
succeeds, missing fields stay absent/None instead of being invented,
and summaries are computed from what is actually present.
"""

import os
import shutil
import tempfile
import unittest

from bankstatementparser.bank_statement_parsers import (
    Camt053Parser,
    process_camt053_folder,
)
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.pain001_parser import Pain001Parser


def _write_xml(content: str) -> str:
    """Write XML content to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# PAIN.001 without the optional GrpHdr block.
PAIN_NO_GRPHDR = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <PmtInf>
      <PmtInfId>PMT001</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt>
      <Dbtr><Nm>Sender</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BIC>BANKDEFFXXX</BIC></FinInstnId></DbtrAgt>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E001</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">100.00</InstdAmt></Amt>
        <Cdtr><Nm>Receiver</Nm></Cdtr>
        <RmtInf><Ustrd>Invoice 001</Ustrd></RmtInf>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""

# PAIN.001 carrying unrecognized vendor/extension tags alongside the
# standard ones.
PAIN_EXTRA_TAGS = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>M1</MsgId>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
      <InitgPty><Nm>TestCo</Nm></InitgPty>
      <CustomTag>ignored</CustomTag>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>PMT001</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt>
      <Dbtr><Nm>Sender</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BIC>BANKDEFFXXX</BIC></FinInstnId></DbtrAgt>
      <ChrgBr>SLEV</ChrgBr>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E001</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">100.00</InstdAmt></Amt>
        <CdtrAgt><FinInstnId><BIC>RCVRBICXXX</BIC></FinInstnId></CdtrAgt>
        <Cdtr><Nm>Receiver</Nm></Cdtr>
        <RmtInf><Ustrd>Invoice 001</Ustrd></RmtInf>
        <SplmtryData>extra</SplmtryData>
        <InstrForCdtrAgt>info</InstrForCdtrAgt>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""

# PAIN.001 where Amt holds EqvtAmt instead of InstdAmt.
PAIN_MISSING_INSTDAMT = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>M1</MsgId>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
      <InitgPty><Nm>TestCo</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>PMT001</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt>
      <Dbtr><Nm>Sender</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BIC>BANKDEFFXXX</BIC></FinInstnId></DbtrAgt>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E001</EndToEndId></PmtId>
        <Amt><EqvtAmt Ccy="EUR">100.00</EqvtAmt></Amt>
        <Cdtr><Nm>Receiver</Nm></Cdtr>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""

# PAIN.001 mixing one EqvtAmt-only transaction with one normal
# InstdAmt transaction.
PAIN_SUMMARY_NO_AMT = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>M1</MsgId>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
      <InitgPty><Nm>TestCo</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>PMT001</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt>
      <Dbtr><Nm>Sender</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BIC>BANKDEFFXXX</BIC></FinInstnId></DbtrAgt>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E001</EndToEndId></PmtId>
        <Amt><EqvtAmt Ccy="EUR">100.00</EqvtAmt></Amt>
        <Cdtr><Nm>Receiver</Nm></Cdtr>
      </CdtTrfTxInf>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E002</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">50.00</InstdAmt></Amt>
        <Cdtr><Nm>Receiver2</Nm></Cdtr>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""

# CAMT statement with an account but no balances and no entries.
CAMT_NO_TRANSACTIONS = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Id>STMT001</Id>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <Acct>
        <Id><IBAN>DE89370400440532013000</IBAN></Id>
      </Acct>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""

# CAMT with only a CLAV balance (no OPBD, no CLBD).
CAMT_NO_OPBD_CLBD = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Id>STMT001</Id>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <Acct>
        <Id><IBAN>DE89370400440532013000</IBAN></Id>
      </Acct>
      <Bal>
        <Tp><CdOrPrtry><Cd>CLAV</Cd></CdOrPrtry></Tp>
        <Amt Ccy="EUR">1000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt><Dt>2024-01-01</Dt></Dt>
      </Bal>
      <Ntry>
        <Amt Ccy="EUR">100.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2024-01-15</Dt></BookgDt>
        <ValDt><Dt>2024-01-15</Dt></ValDt>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""

# CAMT whose entries variously omit Amt or CdtDbtInd.
CAMT_ENTRY_MISSING_AMT = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Id>STMT001</Id>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <Acct>
        <Id><IBAN>DE89370400440532013000</IBAN></Id>
      </Acct>
      <Ntry>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2024-01-15</Dt></BookgDt>
        <ValDt><Dt>2024-01-15</Dt></ValDt>
      </Ntry>
      <Ntry>
        <Amt Ccy="EUR">200.00</Amt>
        <BookgDt><Dt>2024-01-16</Dt></BookgDt>
        <ValDt><Dt>2024-01-16</Dt></ValDt>
      </Ntry>
      <Ntry>
        <Amt Ccy="EUR">300.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2024-01-17</Dt></BookgDt>
        <ValDt><Dt>2024-01-17</Dt></ValDt>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""

# CAMT document with no Stmt at all.
CAMT_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
  </BkToCstmrStmt>
</Document>"""


class TestPain001MissingGrpHdr(unittest.TestCase):
    """GrpHdr is optional; files without it must still parse."""

    def test_parse_without_group_header(self):
        f = _write_xml(PAIN_NO_GRPHDR)
        try:
            parser = Pain001Parser(f)
            df = parser.parse()
            self.assertGreater(len(df), 0)
            self.assertIn("EndToEndId", df.columns)
        finally:
            os.unlink(f)

    def test_get_summary_without_group_header(self):
        f = _write_xml(PAIN_NO_GRPHDR)
        try:
            parser = Pain001Parser(f)
            summary = parser.get_summary()
            self.assertEqual(summary["account_id"], "Unknown")
            self.assertEqual(summary["message_id"], "Unknown")
        finally:
            os.unlink(f)


class TestPain001UnrecognizedTags(unittest.TestCase):
    """Unknown vendor/extension tags are ignored, not fatal."""

    def test_parse_with_extra_tx_children(self):
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            df = parser.parse()
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["EndToEndId"], "E2E001")
            self.assertEqual(df.iloc[0]["CdtrBIC"], "RCVRBICXXX")
        finally:
            os.unlink(f)

    def test_parse_with_extra_grphdr_children(self):
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 1)
            self.assertEqual(payments[0]["MsgId"], "M1")
        finally:
            os.unlink(f)

    def test_streaming_with_extra_tx_children(self):
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 1)
            self.assertEqual(payments[0]["EndToEndId"], "E2E001")
            self.assertEqual(payments[0]["CdtrBIC"], "RCVRBICXXX")
        finally:
            os.unlink(f)


class TestPain001MissingInstdAmt(unittest.TestCase):
    """Amt elements without InstdAmt (e.g. EqvtAmt) are not invented."""

    def test_parse_amt_without_instdamt(self):
        f = _write_xml(PAIN_MISSING_INSTDAMT)
        try:
            parser = Pain001Parser(f)
            df = parser.parse()
            self.assertEqual(len(df), 1)
            self.assertNotIn("InstdAmt", df.columns)
        finally:
            os.unlink(f)

    def test_streaming_amt_without_instdamt(self):
        f = _write_xml(PAIN_MISSING_INSTDAMT)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 1)
            self.assertNotIn("InstdAmt", payments[0])
        finally:
            os.unlink(f)

    def test_get_summary_with_missing_instdamt(self):
        f = _write_xml(PAIN_SUMMARY_NO_AMT)
        try:
            parser = Pain001Parser(f)
            summary = parser.get_summary()
            # Only the second tx carries InstdAmt (50.00)
            self.assertEqual(summary["total_amount"], 50.0)
            self.assertEqual(summary["currency"], "EUR")
        finally:
            os.unlink(f)


class TestPain001StreamingPmtInfData(unittest.TestCase):
    """Streaming mode carries PmtInf-level fields onto each payment."""

    def test_streaming_extracts_pmtinf_data(self):
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 1)
            self.assertEqual(payments[0].get("PmtInfId"), "PMT001")
            self.assertEqual(payments[0].get("PmtMtd"), "TRF")
            self.assertEqual(payments[0].get("DbtrNm"), "Sender")
            self.assertEqual(
                payments[0].get("DbtrIBAN"), "DE89370400440532013000"
            )
            self.assertEqual(payments[0].get("DbtrBIC"), "BANKDEFFXXX")
            self.assertEqual(payments[0].get("ChrgBr"), "SLEV")
        finally:
            os.unlink(f)

    def test_streaming_dbtr_without_nm(self):
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>M1</MsgId>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
      <InitgPty><Nm>TestCo</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>PMT001</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt>
      <Dbtr></Dbtr>
      <DbtrAcct><Id><Othr><Id>OTHER123</Id></Othr></Id></DbtrAcct>
      <DbtrAgt><FinInstnId></FinInstnId></DbtrAgt>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E001</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">100.00</InstdAmt></Amt>
        <Cdtr><Nm>Receiver</Nm></Cdtr>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""
        f = _write_xml(xml)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 1)
            self.assertIsNone(payments[0].get("DbtrNm"))
            self.assertIsNone(payments[0].get("DbtrIBAN"))
            self.assertIsNone(payments[0].get("DbtrBIC"))
        finally:
            os.unlink(f)


class TestPain001GetSummaryEdgeCases(unittest.TestCase):
    """get_summary works from whatever header fields are present."""

    def test_get_summary_unrecognized_grphdr_child(self):
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            summary = parser.get_summary()
            self.assertEqual(summary["initiating_party"], "TestCo")
            self.assertEqual(summary["message_id"], "M1")
        finally:
            os.unlink(f)

    def test_get_summary_amt_child_not_instdamt(self):
        f = _write_xml(PAIN_SUMMARY_NO_AMT)
        try:
            parser = Pain001Parser(f)
            summary = parser.get_summary()
            self.assertEqual(summary["total_amount"], 50.0)
        finally:
            os.unlink(f)


class TestCamtGetSummaryEdgeCases(unittest.TestCase):
    """CAMT get_summary degrades gracefully on sparse statements."""

    def test_get_summary_empty_stats(self):
        f = _write_xml(CAMT_EMPTY)
        try:
            parser = CamtParser(f)
            summary = parser.get_summary()
            self.assertEqual(summary, {})
        finally:
            os.unlink(f)

    def test_get_summary_no_transactions(self):
        f = _write_xml(CAMT_NO_TRANSACTIONS)
        try:
            parser = CamtParser(f)
            summary = parser.get_summary()
            self.assertEqual(summary["transaction_count"], 0)
            self.assertEqual(summary["currency"], "Unknown")
        finally:
            os.unlink(f)

    def test_get_summary_no_balances(self):
        f = _write_xml(CAMT_NO_TRANSACTIONS)
        try:
            parser = CamtParser(f)
            summary = parser.get_summary()
            self.assertNotIn("opening_balance", summary)
            self.assertNotIn("closing_balance", summary)
        finally:
            os.unlink(f)

    def test_get_summary_no_opbd_no_clbd(self):
        f = _write_xml(CAMT_NO_OPBD_CLBD)
        try:
            parser = CamtParser(f)
            summary = parser.get_summary()
            self.assertNotIn("opening_balance", summary)
            self.assertNotIn("closing_balance", summary)
            self.assertEqual(summary["transaction_count"], 1)
        finally:
            os.unlink(f)


class TestCamtStatsEntryMissingFields(unittest.TestCase):
    """Stats count every entry but only sum complete Amt+CdtDbtInd pairs."""

    def test_stats_with_missing_amt_entries(self):
        f = _write_xml(CAMT_ENTRY_MISSING_AMT)
        try:
            parser = CamtParser(f)
            stats = parser.get_statement_stats()
            self.assertEqual(stats.iloc[0]["NumTransactions"], 3)
            # Only the third entry has both Amt and CdtDbtInd
            self.assertEqual(stats.iloc[0]["NetAmount"], 300.0)
        finally:
            os.unlink(f)


class TestBankStatementParsersEdgeCases(unittest.TestCase):
    """Compatibility-wrapper behavior on partial data."""

    def test_camt053_account_not_in_balances(self):
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Id>STMT001</Id>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <Acct>
        <Id><IBAN>DE89370400440532013000</IBAN></Id>
      </Acct>
      <Bal>
        <Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>
        <Amt Ccy="EUR">1000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt><Dt>2024-01-01</Dt></Dt>
      </Bal>
      <Ntry>
        <Amt Ccy="EUR">500.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2024-01-15</Dt></BookgDt>
        <ValDt><Dt>2024-01-15</Dt></ValDt>
      </Ntry>
    </Stmt>
    <Stmt>
      <Id>STMT002</Id>
      <CreDtTm>2024-02-01T00:00:00</CreDtTm>
      <Acct>
        <Id><IBAN>FR7630006000011234567890189</IBAN></Id>
      </Acct>
      <Ntry>
        <Amt Ccy="EUR">200.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <BookgDt><Dt>2024-02-15</Dt></BookgDt>
        <ValDt><Dt>2024-02-15</Dt></ValDt>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        f = _write_xml(xml)
        try:
            with self.assertWarns(DeprecationWarning):
                parser = Camt053Parser(f)
            # The second statement's account has no balances; both
            # statements still survive.
            self.assertEqual(len(parser.statements), 2)
        finally:
            os.unlink(f)

    def test_process_folder_with_subdirectory(self):
        tmpdir = tempfile.mkdtemp()
        try:
            subdir = os.path.join(tmpdir, "subdir")
            os.makedirs(subdir)

            camt_file = os.path.join(tmpdir, "test.xml")
            with open(camt_file, "w", encoding="utf-8") as f:
                f.write(CAMT_NO_TRANSACTIONS)

            files_df, stmts_df, txns_df = process_camt053_folder(tmpdir)
            # Only the XML file is processed, not the subdirectory
            self.assertEqual(len(files_df), 1)
            self.assertEqual(files_df.iloc[0]["FileName"], "test.xml")
        finally:
            shutil.rmtree(tmpdir)


class TestPain001StreamingPiiRedactionMissingFields(unittest.TestCase):
    """Redaction must not fabricate values for absent PII fields."""

    def test_streaming_redact_pii_with_missing_fields(self):
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>M1</MsgId>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>PMT001</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt>
      <Dbtr></Dbtr>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E001</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">100.00</InstdAmt></Amt>
        <Cdtr></Cdtr>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""
        f = _write_xml(xml)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming(redact_pii=True))
            self.assertEqual(len(payments), 1)
            # Absent fields stay None rather than becoming "***REDACTED***"
            self.assertIsNone(payments[0].get("DbtrNm"))
            self.assertIsNone(payments[0].get("CdtrNm"))
        finally:
            os.unlink(f)


class TestPain001SummaryTxNoAmt(unittest.TestCase):
    """A transaction with no Amt element contributes nothing to totals."""

    def test_get_summary_tx_without_amt_element(self):
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>M1</MsgId>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <NbOfTxs>2</NbOfTxs>
      <InitgPty><Nm>TestCo</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>PMT001</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>2</NbOfTxs>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt>
      <Dbtr><Nm>Sender</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BIC>BANKDEFFXXX</BIC></FinInstnId></DbtrAgt>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E001</EndToEndId></PmtId>
        <Cdtr><Nm>Receiver1</Nm></Cdtr>
        <RmtInf><Ustrd>NoAmount</Ustrd></RmtInf>
      </CdtTrfTxInf>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E002</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">75.00</InstdAmt></Amt>
        <Cdtr><Nm>Receiver2</Nm></Cdtr>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""
        f = _write_xml(xml)
        try:
            parser = Pain001Parser(f)
            summary = parser.get_summary()
            self.assertEqual(summary["total_amount"], 75.0)
            self.assertEqual(summary["currency"], "EUR")
        finally:
            os.unlink(f)


if __name__ == "__main__":
    unittest.main()
