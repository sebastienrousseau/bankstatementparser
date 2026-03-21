"""
Tests targeting all remaining partial branch coverage gaps.

Covers partial branches in: pain001_parser.py, camt_parser.py,
bank_statement_parsers.py.
"""

import os
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
    fd, path = tempfile.mkstemp(suffix='.xml')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


# ── Pain001Parser: parse() with missing GrpHdr (150->161) ──────────

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

# ── Pain001 with unrecognized child tags in tx (194->188, 203->188) ──

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

# ── Pain001 with Amt but missing InstdAmt (194->188 false branch) ──

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

# ── Pain001 without GrpHdr for get_summary (402->401) ──────────────

PAIN_NO_GRPHDR_SUMMARY = PAIN_NO_GRPHDR

# ── Pain001 with Amt missing InstdAmt in summary (443->448, 448->440) ──

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

# ── CAMT with no transactions (empty stats) ─────────────────────────

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

# ── CAMT with only CLAV balance (no OPBD, no CLBD) ──────────────────

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

# ── CAMT with entry missing Amt in stats (486->482) ──────────────────

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

# ── CAMT with empty document (no Stmt) ──────────────────────────────

CAMT_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
  </BkToCstmrStmt>
</Document>"""


class TestPain001ParseMissingGrpHdr(unittest.TestCase):
    """Cover pain001_parser.py:150->161 (group_header is None)."""

    def test_parse_without_group_header(self):
        f = _write_xml(PAIN_NO_GRPHDR)
        try:
            parser = Pain001Parser(f)
            df = parser.parse()
            # Should still parse payments, just without header fields
            self.assertGreater(len(df), 0)
            self.assertIn('EndToEndId', df.columns)
        finally:
            os.unlink(f)

    def test_get_summary_without_group_header(self):
        """Cover pain001_parser.py:402->401 (group_header None in get_summary)."""
        f = _write_xml(PAIN_NO_GRPHDR)
        try:
            parser = Pain001Parser(f)
            summary = parser.get_summary()
            self.assertEqual(summary['account_id'], 'Unknown')
            self.assertEqual(summary['message_id'], 'Unknown')
        finally:
            os.unlink(f)


class TestPain001UnrecognizedTags(unittest.TestCase):
    """Cover pain001_parser.py implicit else branches for unrecognized XML child tags."""

    def test_parse_with_extra_tx_children(self):
        """Cover 194->188, 203->188: unrecognized child tags in tx loop."""
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            df = parser.parse()
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]['EndToEndId'], 'E2E001')
            self.assertEqual(df.iloc[0]['CdtrBIC'], 'RCVRBICXXX')
        finally:
            os.unlink(f)

    def test_parse_with_extra_grphdr_children(self):
        """Cover 293->290: unrecognized child in GrpHdr (streaming)."""
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 1)
            # Header fields should be extracted despite extra tags
            self.assertEqual(payments[0]['MsgId'], 'M1')
        finally:
            os.unlink(f)

    def test_streaming_with_extra_tx_children(self):
        """Cover 382->376, 391->376: unrecognized child in streaming tx."""
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 1)
            self.assertEqual(payments[0]['EndToEndId'], 'E2E001')
            self.assertEqual(payments[0]['CdtrBIC'], 'RCVRBICXXX')
        finally:
            os.unlink(f)


class TestPain001MissingInstdAmt(unittest.TestCase):
    """Cover pain001_parser.py:194->188 (InstdAmt not found in Amt element)."""

    def test_parse_amt_without_instdamt(self):
        f = _write_xml(PAIN_MISSING_INSTDAMT)
        try:
            parser = Pain001Parser(f)
            df = parser.parse()
            self.assertEqual(len(df), 1)
            # InstdAmt should not be set since there's no InstdAmt element
            self.assertNotIn('InstdAmt', df.columns)
        finally:
            os.unlink(f)

    def test_streaming_amt_without_instdamt(self):
        """Cover streaming false branch for missing InstdAmt."""
        f = _write_xml(PAIN_MISSING_INSTDAMT)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 1)
            self.assertNotIn('InstdAmt', payments[0])
        finally:
            os.unlink(f)

    def test_get_summary_with_missing_instdamt(self):
        """Cover 423->433, 428->425, 443->448, 448->440 in get_summary."""
        f = _write_xml(PAIN_SUMMARY_NO_AMT)
        try:
            parser = Pain001Parser(f)
            summary = parser.get_summary()
            # Only the second tx has InstdAmt with 50.00
            self.assertEqual(summary['total_amount'], 50.0)
            self.assertEqual(summary['currency'], 'EUR')
        finally:
            os.unlink(f)


class TestPain001StreamingPmtInfData(unittest.TestCase):
    """Cover streaming PmtInf-level data extraction (314->286, 322->286, 330->286)."""

    def test_streaming_extracts_pmtinf_data(self):
        """Verify streaming mode extracts PmtInfId, DbtrNm, DbtrIBAN, DbtrBIC."""
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 1)
            # Verify PmtInf-level data was extracted
            self.assertEqual(payments[0].get('PmtInfId'), 'PMT001')
            self.assertEqual(payments[0].get('PmtMtd'), 'TRF')
            self.assertEqual(payments[0].get('DbtrNm'), 'Sender')
            self.assertEqual(payments[0].get('DbtrIBAN'), 'DE89370400440532013000')
            self.assertEqual(payments[0].get('DbtrBIC'), 'BANKDEFFXXX')
            self.assertEqual(payments[0].get('ChrgBr'), 'SLEV')
        finally:
            os.unlink(f)

    def test_streaming_dbtr_without_nm(self):
        """Cover false branch where Dbtr has no Nm child."""
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
            # Dbtr has no Nm, should be None
            self.assertIsNone(payments[0].get('DbtrNm'))
            # DbtrAcct has no IBAN, should be None
            self.assertIsNone(payments[0].get('DbtrIBAN'))
            # DbtrAgt has no BIC, should be None
            self.assertIsNone(payments[0].get('DbtrBIC'))
        finally:
            os.unlink(f)


class TestPain001GetSummaryEdgeCases(unittest.TestCase):
    """Cover get_summary partial branches."""

    def test_get_summary_unrecognized_grphdr_child(self):
        """Cover 409->406: InitgPty child iteration with unrecognized tags."""
        # PAIN_EXTRA_TAGS has <CustomTag>ignored</CustomTag> in GrpHdr
        f = _write_xml(PAIN_EXTRA_TAGS)
        try:
            parser = Pain001Parser(f)
            summary = parser.get_summary()
            self.assertEqual(summary['initiating_party'], 'TestCo')
            self.assertEqual(summary['message_id'], 'M1')
        finally:
            os.unlink(f)

    def test_get_summary_amt_child_not_instdamt(self):
        """Cover 423->433: tx child is Amt but doesn't contain InstdAmt.
        Also 428->425, 443->448, 448->440."""
        f = _write_xml(PAIN_SUMMARY_NO_AMT)
        try:
            parser = Pain001Parser(f)
            summary = parser.get_summary()
            # First tx has EqvtAmt (no InstdAmt), second has InstdAmt=50.00
            self.assertEqual(summary['total_amount'], 50.0)
        finally:
            os.unlink(f)


class TestCamtGetSummaryEdgeCases(unittest.TestCase):
    """Cover camt_parser.py get_summary partial branches."""

    def test_get_summary_empty_stats(self):
        """Cover 708->724: stats_df is empty."""
        f = _write_xml(CAMT_EMPTY)
        try:
            parser = CamtParser(f)
            summary = parser.get_summary()
            # With no statements, summary should be minimal
            self.assertEqual(summary, {})
        finally:
            os.unlink(f)

    def test_get_summary_no_transactions(self):
        """Cover 720->724: transactions is empty."""
        f = _write_xml(CAMT_NO_TRANSACTIONS)
        try:
            parser = CamtParser(f)
            summary = parser.get_summary()
            self.assertEqual(summary['transaction_count'], 0)
            self.assertEqual(summary['currency'], 'Unknown')
        finally:
            os.unlink(f)

    def test_get_summary_no_balances(self):
        """Cover 724->734: balances_df is empty."""
        f = _write_xml(CAMT_NO_TRANSACTIONS)
        try:
            parser = CamtParser(f)
            summary = parser.get_summary()
            self.assertNotIn('opening_balance', summary)
            self.assertNotIn('closing_balance', summary)
        finally:
            os.unlink(f)

    def test_get_summary_no_opbd_no_clbd(self):
        """Cover 729->731, 731->734: balances exist but no OPBD/CLBD codes."""
        f = _write_xml(CAMT_NO_OPBD_CLBD)
        try:
            parser = CamtParser(f)
            summary = parser.get_summary()
            # Has CLAV balance but no OPBD or CLBD
            self.assertNotIn('opening_balance', summary)
            self.assertNotIn('closing_balance', summary)
            self.assertEqual(summary['transaction_count'], 1)
        finally:
            os.unlink(f)


class TestCamtStatsEntryMissingFields(unittest.TestCase):
    """Cover camt_parser.py:486->482 (entry missing Amt or CdtDbtInd in stats)."""

    def test_stats_with_missing_amt_entries(self):
        """Entry without Amt should be counted but not included in net amount."""
        f = _write_xml(CAMT_ENTRY_MISSING_AMT)
        try:
            parser = CamtParser(f)
            stats = parser.get_statement_stats()
            self.assertEqual(stats.iloc[0]['NumTransactions'], 3)
            # Only the third entry has both Amt and CdtDbtInd
            self.assertEqual(stats.iloc[0]['NetAmount'], 300.0)
        finally:
            os.unlink(f)


class TestBankStatementParsersEdgeCases(unittest.TestCase):
    """Cover bank_statement_parsers.py partial branches."""

    def test_camt053_account_not_in_balances(self):
        """Cover 240->238: account_id not in balances_by_account."""
        # Create CAMT with two statements: one with balances, one without
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
            parser = Camt053Parser(f)
            # Second statement's account ID should not be in balances_by_account
            self.assertEqual(len(parser.statements), 2)
        finally:
            os.unlink(f)

    def test_process_folder_with_subdirectory(self):
        """Cover 285->283: subdirectory in folder (os.path.isfile returns False)."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Create a subdirectory inside the folder
            subdir = os.path.join(tmpdir, 'subdir')
            os.makedirs(subdir)

            # Create a valid CAMT file
            camt_file = os.path.join(tmpdir, 'test.xml')
            with open(camt_file, 'w', encoding='utf-8') as f:
                f.write(CAMT_NO_TRANSACTIONS)

            files_df, stmts_df, txns_df = process_camt053_folder(tmpdir)
            # Only the XML file should be processed (not the subdirectory)
            self.assertEqual(len(files_df), 1)
            self.assertEqual(files_df.iloc[0]['FileName'], 'test.xml')
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class TestPain001StreamingPiiRedactionMissingFields(unittest.TestCase):
    """Cover pain001_parser.py:402->401 (PII field missing/None in redaction)."""

    def test_streaming_redact_pii_with_missing_fields(self):
        """When redact_pii=True but some PII fields are None/missing."""
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
            # DbtrNm is None, CdtrNm is None, DbtrIBAN is None, InitgPty is None
            # These should NOT be redacted (they're falsy)
            self.assertIsNone(payments[0].get('DbtrNm'))
            self.assertIsNone(payments[0].get('CdtrNm'))
        finally:
            os.unlink(f)


class TestPain001SummaryTxNoAmt(unittest.TestCase):
    """Cover pain001_parser.py:443->448 (tx with no Amt child element)."""

    def test_get_summary_tx_without_amt_element(self):
        """Transaction with no Amt child at all in get_summary."""
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
            # Only second tx has Amt, so total should be 75.0
            self.assertEqual(summary['total_amount'], 75.0)
            self.assertEqual(summary['currency'], 'EUR')
        finally:
            os.unlink(f)


if __name__ == '__main__':
    unittest.main()
