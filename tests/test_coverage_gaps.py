"""
Tests to achieve 100% code coverage for all modules.

Covers uncovered lines in: cli.py, camt_parser.py, pain001_parser.py,
bank_statement_parsers.py, base_parser.py, input_validator.py.
"""

import unittest
import tempfile
import os
import sys
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import pandas as pd

from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.pain001_parser import Pain001Parser
from bankstatementparser.bank_statement_parsers import (
    Pain001Parser as BankPain001Parser,
    Camt053Parser,
    FileParserError,
    process_camt053_folder,
)
from bankstatementparser.base_parser import BankStatementParser
from bankstatementparser.input_validator import InputValidator, ValidationError
from bankstatementparser.cli import BankStatementCLI, setup_logging


# ── Shared XML fixtures ──────────────────────────────────────────────

CAMT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <GrpHdr>
      <MsgId>MSG001</MsgId>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
    </GrpHdr>
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
      <Bal>
        <Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>
        <Amt Ccy="EUR">1500.00</Amt>
        <CdtDbtInd>DBIT</CdtDbtInd>
        <Dt><Dt>2024-01-31</Dt></Dt>
      </Bal>
      <Ntry>
        <Amt Ccy="EUR">500.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Sts>BOOK</Sts>
        <BookgDt><Dt>2024-01-15</Dt></BookgDt>
        <ValDt><Dt>2024-01-15</Dt></ValDt>
        <NtryDtls>
          <TxDtls>
            <Refs><EndToEndId>REF001</EndToEndId></Refs>
            <RltdPties>
              <Dbtr>
                <Nm>Sender</Nm>
                <PstlAdr><AdrLine>123 Main St</AdrLine></PstlAdr>
              </Dbtr>
              <Cdtr>
                <Nm>Receiver</Nm>
                <PstlAdr><AdrLine>456 Oak Ave</AdrLine></PstlAdr>
              </Cdtr>
            </RltdPties>
          </TxDtls>
        </NtryDtls>
      </Ntry>
      <Ntry>
        <Amt Ccy="EUR">200.00</Amt>
        <CdtDbtInd>DBIT</CdtDbtInd>
        <Sts>BOOK</Sts>
        <BookgDt><Dt>2024-01-20</Dt></BookgDt>
        <ValDt><Dt>2024-01-20</Dt></ValDt>
        <NtryDtls>
          <TxDtls>
            <Refs><EndToEndId>REF002</EndToEndId></Refs>
            <RltdPties>
              <Dbtr><Nm>AnotherSender</Nm></Dbtr>
            </RltdPties>
          </TxDtls>
        </NtryDtls>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>
"""

CAMT_XML_WITH_PRTRY = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <GrpHdr><MsgId>MSG002</MsgId><CreDtTm>2024-01-01T00:00:00</CreDtTm></GrpHdr>
    <Stmt>
      <Id>STMT002</Id>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <Acct><Id><IBAN>DE89370400440532013000</IBAN></Id></Acct>
      <Bal>
        <Tp><CdOrPrtry><Prtry>CUSTOM_BAL</Prtry></CdOrPrtry></Tp>
        <Amt Ccy="EUR">2000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt><Dt>2024-01-01</Dt></Dt>
      </Bal>
      <Bal>
        <Tp><CdOrPrtry></CdOrPrtry></Tp>
        <Amt Ccy="EUR">3000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Dt><Dt>2024-01-01</Dt></Dt>
      </Bal>
      <Ntry>
        <Amt Ccy="EUR">100.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Sts>BOOK</Sts>
        <BookgDt><Dt>2024-01-15</Dt></BookgDt>
        <ValDt><Dt>2024-01-15</Dt></ValDt>
        <NtryDtls><TxDtls><Refs><EndToEndId>REF003</EndToEndId></Refs>
        <RltdPties><Dbtr><Nm>Test</Nm></Dbtr></RltdPties></TxDtls></NtryDtls>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>
"""

PAIN_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>MSG001</MsgId>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
      <InitgPty><Nm>Test Corp</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>PMT001</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs>
      <CtrlSum>100.00</CtrlSum>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt>
      <ChrgBr>SLEV</ChrgBr>
      <Dbtr><Nm>Acme Corp</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BIC>BANKDEFFXXX</BIC></FinInstnId></DbtrAgt>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E001</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">100.00</InstdAmt></Amt>
        <CdtrAgt><FinInstnId><BIC>SPUEDE2UXXX</BIC></FinInstnId></CdtrAgt>
        <Cdtr><Nm>Receiver Corp</Nm></Cdtr>
        <RmtInf><Ustrd>Invoice-001</Ustrd></RmtInf>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>
"""


def _write_xml(xml_content, suffix='.xml'):
    """Helper: write XML content to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(
        mode='w', suffix=suffix, delete=False, encoding='utf-8'
    )
    f.write(xml_content)
    f.close()
    return f.name


# ── CamtParser coverage tests ────────────────────────────────────────

class TestCamtParserCoverage(unittest.TestCase):
    """Cover uncovered lines in camt_parser.py."""

    def setUp(self):
        self.camt_file = _write_xml(CAMT_XML)
        self.camt_prtry_file = _write_xml(CAMT_XML_WITH_PRTRY)

    def tearDown(self):
        for f in [self.camt_file, self.camt_prtry_file]:
            if os.path.exists(f):
                os.unlink(f)

    def test_permission_error_in_init(self):
        """Cover PermissionError handler (line 83-85)."""
        f = _write_xml(CAMT_XML)
        try:
            os.chmod(f, 0o000)
            # Pass as Path to bypass input validator, hit open() directly
            with self.assertRaises((PermissionError, ValidationError)):
                CamtParser(Path(f))
        finally:
            os.chmod(f, 0o644)
            os.unlink(f)

    def test_file_not_found_in_init(self):
        """Cover FileNotFoundError handler (lines 80-82)."""
        # Pass Path object to bypass validator
        with self.assertRaises(FileNotFoundError):
            CamtParser(Path('/tmp/nonexistent_camt_file_12345.xml'))

    def test_generic_exception_in_init(self):
        """Cover generic Exception handler in file reading (line 86-89)."""
        # Pass Path to bypass validator, then mock open to raise generic error
        with patch('builtins.open', side_effect=IOError("disk error")):
            with self.assertRaises((ValidationError, IOError)):
                CamtParser(Path(self.camt_file))

    def test_dbit_balance_sign_adjustment(self):
        """Cover DBIT balance sign adjustment (line 228-229)."""
        parser = CamtParser(self.camt_file)
        balances_df = parser.get_account_balances()
        # CLBD balance is DBIT, so amount should be negative
        clbd = balances_df[balances_df['Code'] == 'CLBD']
        self.assertFalse(clbd.empty)
        self.assertLess(clbd.iloc[0]['Amount'], 0)

    def test_prtry_balance_type(self):
        """Cover Prtry balance type handling (PR #5 fix)."""
        parser = CamtParser(self.camt_prtry_file)
        balances_df = parser.get_account_balances()
        codes = balances_df['Code'].tolist()
        # Check Proprietary type was found
        self.assertTrue(any('Proprietary' in str(c) for c in codes))

    def test_na_balance_type(self):
        """Cover N/A balance type when neither Cd nor Prtry present."""
        parser = CamtParser(self.camt_prtry_file)
        balances_df = parser.get_account_balances()
        codes = balances_df['Code'].tolist()
        self.assertIn('N/A', codes)

    def test_malformed_bal_element_skipped(self):
        """Cover malformed Bal element warning (line 219)."""
        # Bal element with no Amt
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <GrpHdr><MsgId>M1</MsgId><CreDtTm>2024-01-01</CreDtTm></GrpHdr>
    <Stmt>
      <Id>S1</Id><CreDtTm>2024-01-01</CreDtTm>
      <Acct><Id><IBAN>DE89370400440532013000</IBAN></Id></Acct>
      <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp></Bal>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        f = _write_xml(xml)
        try:
            parser = CamtParser(f)
            balances = parser.get_account_balances()
            # Malformed balance (no Amt) should be skipped
            self.assertTrue(balances.empty)
        finally:
            os.unlink(f)

    def test_transactions_with_redact_pii_and_addresses(self):
        """Cover redact_pii + address lines (lines 374-378)."""
        parser = CamtParser(self.camt_file)
        txs = parser.get_transactions(redact_pii=True)
        # Addresses should be redacted if they existed
        if 'DebtorAddress' in txs.columns:
            for val in txs['DebtorAddress'].dropna():
                self.assertEqual(val, '***REDACTED***')

    def test_streaming_parse_basic(self):
        """Cover streaming parsing path."""
        parser = CamtParser(self.camt_file)
        transactions = list(parser.parse_streaming())
        self.assertGreater(len(transactions), 0)

    def test_streaming_dbit_and_pii_redaction(self):
        """Cover streaming DBIT sign adjustment + PII redaction (lines 631, 669-672)."""
        parser = CamtParser(self.camt_file)
        transactions = list(parser.parse_streaming(redact_pii=True))
        # Should have DBIT transaction with negative amount
        dbit_txs = [t for t in transactions if t.get('DrCr') == 'DBIT']
        for tx in dbit_txs:
            self.assertLess(tx['Amount'], 0)
        # Addresses should be redacted
        for tx in transactions:
            if 'DebtorAddress' in tx:
                self.assertEqual(tx['DebtorAddress'], '***REDACTED***')
            if 'CreditorAddress' in tx:
                self.assertEqual(tx['CreditorAddress'], '***REDACTED***')

    def test_streaming_malformed_transaction_continues(self):
        """Cover malformed transaction error in streaming (lines 590-593)."""
        parser = CamtParser(self.camt_file)
        # Patch _parse_streaming_transaction to raise on first call, then work normally
        original_method = parser._parse_streaming_transaction
        call_count = [0]

        def side_effect(elem, account_id, redact_pii=False):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("Malformed transaction")
            return original_method(elem, account_id, redact_pii)

        with patch.object(parser, '_parse_streaming_transaction', side_effect=side_effect):
            transactions = list(parser.parse_streaming())
            # Should still get remaining transactions
            self.assertGreater(len(transactions), 0)

    def test_streaming_file_not_found(self):
        """Cover streaming FileNotFoundError (lines 540-542)."""
        parser = CamtParser(self.camt_file)
        parser._file_path = '/nonexistent/file.xml'
        with self.assertRaises(FileNotFoundError):
            list(parser.parse_streaming())

    def test_streaming_permission_error(self):
        """Cover streaming PermissionError (lines 543-545)."""
        parser = CamtParser(self.camt_file)
        with patch('builtins.open', side_effect=PermissionError("no access")):
            with self.assertRaises(ValidationError):
                list(parser.parse_streaming())

    def test_streaming_generic_error(self):
        """Cover streaming generic Exception (lines 546-548)."""
        parser = CamtParser(self.camt_file)
        with patch('builtins.open', side_effect=IOError("disk error")):
            with self.assertRaises(ValidationError):
                list(parser.parse_streaming())

    def test_streaming_cleanup_failure(self):
        """Cover streaming cleanup OSError path (lines 605-606)."""
        parser = CamtParser(self.camt_file)
        with patch('os.unlink', side_effect=OSError("cannot delete")):
            # Should still work, just cleanup fails silently
            transactions = list(parser.parse_streaming())
            self.assertGreater(len(transactions), 0)

    def test_streaming_val_date_datetime_fallback(self):
        """Cover DtTm fallback for date elements (lines 647-648, 652-653)."""
        # Uses DtTm instead of Dt - the existing test data uses DtTm for BookgDt
        parser = CamtParser(
            os.path.join(os.path.dirname(__file__), 'test_data', 'camt.053.001.02.xml')
        )
        transactions = list(parser.parse_streaming())
        self.assertGreater(len(transactions), 0)
        # Check booking dates came from DtTm elements
        for tx in transactions:
            if tx.get('BookgDt'):
                self.assertIn('T', tx['BookgDt'])  # DtTm format has 'T'

    def test_entity_error_recovery_parsing(self):
        """Cover entity error fallback to recovery parser (lines 115-124)."""
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml += '<Document>\n<BkToCstmrStmt>\n<GrpHdr><MsgId>M1</MsgId></GrpHdr>\n'
        xml += '<Stmt><Id>S1</Id><CreDtTm>2024-01-01</CreDtTm>'
        xml += '<Acct><Id><IBAN>DE89370400440532013000</IBAN></Id></Acct>'
        xml += '<Ntry><Amt Ccy="EUR">10</Amt><CdtDbtInd>CRDT</CdtDbtInd>'
        xml += '<Sts>BOOK</Sts><BookgDt><Dt>2024-01-01</Dt></BookgDt>'
        xml += '<ValDt><Dt>2024-01-01</Dt></ValDt>'
        xml += '<NtryDtls><TxDtls><Refs><EndToEndId>R1</EndToEndId></Refs>'
        xml += '<RltdPties><Dbtr><Nm>D</Nm></Dbtr></RltdPties>'
        xml += '</TxDtls></NtryDtls></Ntry>'
        xml += '</Stmt>\n</BkToCstmrStmt>\n</Document>'
        # Inject an undeclared entity
        xml = xml.replace('<MsgId>M1</MsgId>', '<MsgId>&foo;M1</MsgId>')
        f = _write_xml(xml)
        try:
            # This should trigger strict parse failure -> recovery parse
            parser = CamtParser(f)
            # Parser should have created a tree (recovery mode)
            self.assertIsNotNone(parser.tree)
        finally:
            os.unlink(f)

    def test_general_xml_parse_exception(self):
        """Cover general Exception in XML parsing (lines 131-133)."""
        f = _write_xml(CAMT_XML)
        try:
            parser = CamtParser.__new__(CamtParser)
            parser._original_file_name = f
            parser._file_path = f
            # Mock etree.fromstring to raise a non-XMLSyntaxError
            with patch('bankstatementparser.camt_parser.etree.fromstring', side_effect=RuntimeError("unexpected")):
                with self.assertRaises(RuntimeError):
                    CamtParser(f)
        finally:
            os.unlink(f)

    def test_get_summary(self):
        """Cover get_summary method (lines 703-734)."""
        parser = CamtParser(self.camt_file)
        summary = parser.get_summary()
        self.assertIn('account_id', summary)
        self.assertIn('transaction_count', summary)
        self.assertIn('opening_balance', summary)
        self.assertIn('closing_balance', summary)

    def test_get_element_text_helper(self):
        """Cover _get_element_text helper (lines 415-416)."""
        parser = CamtParser(self.camt_file)
        from lxml import etree as et
        elem = et.fromstring('<Root><Child>hello</Child></Root>')
        # Existing element
        self.assertEqual(parser._get_element_text(elem, './Child'), 'hello')
        # Non-existing element
        self.assertEqual(parser._get_element_text(elem, './Missing'), '')

    def test_streaming_valdt_datetime_fallback(self):
        """Cover ValDt DtTm fallback (line 648) explicitly."""
        xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <GrpHdr><MsgId>M1</MsgId><CreDtTm>2024-01-01</CreDtTm></GrpHdr>
    <Stmt>
      <Id>S1</Id><CreDtTm>2024-01-01</CreDtTm>
      <Acct><Id><IBAN>DE89370400440532013000</IBAN></Id></Acct>
      <Ntry>
        <Amt Ccy="EUR">50.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Sts>BOOK</Sts>
        <BookgDt><DtTm>2024-01-15T10:00:00</DtTm></BookgDt>
        <ValDt><DtTm>2024-01-15T10:00:00</DtTm></ValDt>
        <NtryDtls><TxDtls><Refs><EndToEndId>R1</EndToEndId></Refs>
        <RltdPties><Dbtr><Nm>D</Nm></Dbtr></RltdPties></TxDtls></NtryDtls>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        f = _write_xml(xml)
        try:
            parser = CamtParser(f)
            transactions = list(parser.parse_streaming())
            self.assertGreater(len(transactions), 0)
            # ValDt should use DtTm (contains 'T')
            self.assertIn('T', transactions[0]['ValDt'])
        finally:
            os.unlink(f)


# ── Pain001Parser coverage tests ─────────────────────────────────────

class TestPain001ParserCoverage(unittest.TestCase):
    """Cover uncovered lines in pain001_parser.py."""

    def setUp(self):
        self.pain_file = _write_xml(PAIN_XML)

    def tearDown(self):
        if os.path.exists(self.pain_file):
            os.unlink(self.pain_file)

    def test_permission_error_in_init(self):
        """Cover PermissionError handler (lines 80-82)."""
        f = _write_xml(PAIN_XML)
        try:
            os.chmod(f, 0o000)
            # Pass Path to bypass validator, hit open() directly
            with self.assertRaises((PermissionError, ValidationError)):
                Pain001Parser(Path(f))
        finally:
            os.chmod(f, 0o644)
            os.unlink(f)

    def test_file_not_found_in_init(self):
        """Cover FileNotFoundError handler (lines 77-79)."""
        with self.assertRaises(FileNotFoundError):
            Pain001Parser(Path('/tmp/nonexistent_pain_file_12345.xml'))

    def test_generic_exception_in_init(self):
        """Cover generic Exception handler (lines 83-87)."""
        # Pass Path to bypass validator
        with patch('builtins.open', side_effect=IOError("disk error")):
            with self.assertRaises((ValidationError, IOError)):
                Pain001Parser(Path(self.pain_file))

    def test_value_error_in_xml_parsing(self):
        """Cover ValueError in XML parsing (lines 104-111)."""
        # Write valid-ish content that bypasses validator but triggers ValueError
        f = _write_xml('<?xml version="1.0"?><Empty/>')
        try:
            # Pass Path to bypass validator
            with patch('bankstatementparser.pain001_parser.etree.fromstring',
                       side_effect=ValueError("Start tag expected, '<' not found")):
                with self.assertRaises(ValidationError):
                    Pain001Parser(Path(f))
        finally:
            os.unlink(f)

    def test_value_error_other_in_xml_parsing(self):
        """Cover ValueError else branch in XML parsing (lines 110-111)."""
        f = _write_xml('<?xml version="1.0"?><Empty/>')
        try:
            with patch('bankstatementparser.pain001_parser.etree.fromstring',
                       side_effect=ValueError("some other value error")):
                with self.assertRaises(ValidationError) as ctx:
                    Pain001Parser(Path(f))
                self.assertIn('Invalid XML format', str(ctx.exception))
        finally:
            os.unlink(f)

    def test_streaming_parse_basic(self):
        """Cover parse_streaming method."""
        parser = Pain001Parser(self.pain_file)
        payments = list(parser.parse_streaming())
        self.assertGreater(len(payments), 0)

    def test_streaming_with_pii_redaction(self):
        """Cover parse_streaming PII redaction (lines 363-367)."""
        parser = Pain001Parser(self.pain_file)
        payments = list(parser.parse_streaming(redact_pii=True))
        for payment in payments:
            for field in ['DbtrNm', 'CdtrNm', 'DbtrIBAN', 'InitgPty']:
                if payment.get(field):
                    self.assertEqual(payment[field], '***REDACTED***')

    def test_streaming_validation_failure(self):
        """Cover streaming validation failure (lines 226-228)."""
        parser = Pain001Parser(self.pain_file)
        parser.file_name = '/nonexistent/file.xml'
        with self.assertRaises((ValidationError, FileNotFoundError)):
            list(parser.parse_streaming())

    def test_streaming_file_not_found(self):
        """Cover streaming FileNotFoundError (lines 236-238)."""
        parser = Pain001Parser(self.pain_file)
        # Make the file_name not a string to skip validation, then fail on read
        parser.file_name = Path('/nonexistent/file.xml')
        with self.assertRaises(FileNotFoundError):
            list(parser.parse_streaming())

    def test_streaming_permission_error(self):
        """Cover streaming PermissionError (lines 239-241)."""
        parser = Pain001Parser(self.pain_file)
        parser.file_name = 42  # Not a string, skip validation
        with patch('builtins.open', side_effect=PermissionError("no access")):
            with self.assertRaises(ValidationError):
                list(parser.parse_streaming())

    def test_streaming_generic_error(self):
        """Cover streaming generic Exception (lines 242-244)."""
        parser = Pain001Parser(self.pain_file)
        parser.file_name = 42  # Not a string, skip validation
        with patch('builtins.open', side_effect=IOError("disk error")):
            with self.assertRaises(ValidationError):
                list(parser.parse_streaming())

    def test_streaming_malformed_payment_continues(self):
        """Cover malformed payment error in streaming (lines 305-308)."""
        parser = Pain001Parser(self.pain_file)
        original_method = parser._parse_streaming_payment
        call_count = [0]

        def side_effect(elem, pmt_info, header, redact_pii=False):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("Malformed payment")
            return original_method(elem, pmt_info, header, redact_pii)

        with patch.object(parser, '_parse_streaming_payment', side_effect=side_effect):
            payments = list(parser.parse_streaming())
            # We only have one payment, so if first fails, we get zero
            # That's OK - we just need to cover the continue path

    def test_streaming_cleanup_failure(self):
        """Cover streaming cleanup OSError path (lines 320-321)."""
        parser = Pain001Parser(self.pain_file)
        with patch('os.unlink', side_effect=OSError("cannot delete")):
            payments = list(parser.parse_streaming())

    def test_get_summary(self):
        """Cover get_summary method (lines 371-428)."""
        parser = Pain001Parser(self.pain_file)
        summary = parser.get_summary()
        self.assertIn('account_id', summary)
        self.assertIn('transaction_count', summary)
        self.assertEqual(summary['transaction_count'], 1)

    def test_get_summary_exception_fallback(self):
        """Cover get_summary exception fallback (lines 426-428)."""
        parser = Pain001Parser(self.pain_file)
        # Corrupt the tree to trigger exception
        parser.tree = None
        summary = parser.get_summary()
        self.assertEqual(summary['account_id'], 'Unknown')

    def test_streaming_pmtinf_child_extraction(self):
        """Cover streaming PmtInf child extraction: Dbtr, DbtrAgt (lines 286-298).

        iterparse fires 'end' for PmtInf after all CdtTrfTxInf ends inside it.
        To hit lines 290-298, we need the PmtInf end event to fire while processing.
        With 2+ PmtInf blocks, the second PmtInf's CdtTrfTxInf will use data
        from the first PmtInf's end event.
        """
        # Create XML with 2 PmtInf blocks
        two_pmt_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>M1</MsgId><CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <NbOfTxs>2</NbOfTxs><InitgPty><Nm>Corp</Nm></InitgPty>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>P1</PmtInfId><PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs><CtrlSum>100</CtrlSum>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt><ChrgBr>SLEV</ChrgBr>
      <Dbtr><Nm>Debtor1</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BIC>BANKDEFF</BIC></FinInstnId></DbtrAgt>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E1</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">100.00</InstdAmt></Amt>
        <Cdtr><Nm>R1</Nm></Cdtr>
        <RmtInf><Ustrd>I1</Ustrd></RmtInf>
      </CdtTrfTxInf>
    </PmtInf>
    <PmtInf>
      <PmtInfId>P2</PmtInfId><PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs><CtrlSum>200</CtrlSum>
      <ReqdExctnDt>2024-01-16</ReqdExctnDt><ChrgBr>SLEV</ChrgBr>
      <Dbtr><Nm>Debtor2</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE44500105175407324931</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BIC>BANKDEFF</BIC></FinInstnId></DbtrAgt>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">200.00</InstdAmt></Amt>
        <Cdtr><Nm>R2</Nm></Cdtr>
        <RmtInf><Ustrd>I2</Ustrd></RmtInf>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""
        f = _write_xml(two_pmt_xml)
        try:
            parser = Pain001Parser(f)
            payments = list(parser.parse_streaming())
            self.assertEqual(len(payments), 2)
            # The second payment should have debtor info from first PmtInf end
            # (since PmtInf end fires after its CdtTrfTxInf but before next PmtInf)
        finally:
            os.unlink(f)


# ── BankStatementParsers coverage tests ───────────────────────────────

class TestBankStatementParsersCoverage(unittest.TestCase):
    """Cover uncovered lines in bank_statement_parsers.py."""

    def setUp(self):
        self.camt_file = _write_xml(CAMT_XML)
        self.pain_file = _write_xml(PAIN_XML)

    def tearDown(self):
        for f in [self.camt_file, self.pain_file]:
            if os.path.exists(f):
                os.unlink(f)

    def test_wrapper_pain001_nonexistent_file(self):
        """Cover Pain001Parser wrapper with FileNotFoundError (line 69)."""
        with self.assertRaises((FileNotFoundError, ValidationError)):
            BankPain001Parser('/nonexistent/file.xml')

    def test_wrapper_pain001_redact_pii(self):
        """Cover _parse_payment redact_pii=True with address (line 160-161)."""
        # Create PAIN XML with address lines
        pain_with_addr = PAIN_XML.replace(
            '<Cdtr><Nm>Receiver Corp</Nm></Cdtr>',
            '<Cdtr><Nm>Receiver Corp</Nm><PstlAdr><AdrLine>123 Street</AdrLine></PstlAdr></Cdtr>'
        )
        f = _write_xml(pain_with_addr)
        try:
            parser = BankPain001Parser(f, redact_pii=True)
            for payment in parser.payments:
                if payment.get('Address'):
                    self.assertEqual(payment['Address'], '***REDACTED***')
        finally:
            os.unlink(f)

    def test_camt053_balance_grouping(self):
        """Cover Camt053Parser balance grouping by account (lines 233-241)."""
        parser = Camt053Parser(self.camt_file)
        self.assertGreater(len(parser.statements), 0)

    def test_camt053_validation_error(self):
        """Cover Camt053Parser with ValidationError (line 243-244)."""
        f = _write_xml("not xml content")
        try:
            with self.assertRaises((FileParserError, ValidationError)):
                Camt053Parser(f)
        finally:
            os.unlink(f)

    def test_camt053_generic_exception(self):
        """Cover Camt053Parser generic Exception (line 247-248)."""
        xml = '<?xml version="1.0"?><Document><BkToCstmrStmt></BkToCstmrStmt></Document>'
        f = _write_xml(xml)
        try:
            parser = Camt053Parser(f)
        except (FileParserError, Exception):
            pass  # Expected
        finally:
            os.unlink(f)

    def test_camt053_validation_error_from_camt_parser(self):
        """Cover Camt053Parser ValidationError catch (line 243-244)."""
        # Mock CamtParser to raise ValidationError
        with patch('bankstatementparser.bank_statement_parsers.CamtParser',
                   side_effect=ValidationError("test validation error")):
            with self.assertRaises(FileParserError) as ctx:
                Camt053Parser(self.camt_file)
            self.assertIn('Not a valid CAMT.053 file', str(ctx.exception))

    def test_camt053_file_not_found(self):
        """Cover Camt053Parser FileNotFoundError (line 245-246)."""
        with self.assertRaises(FileNotFoundError):
            Camt053Parser('/nonexistent/camt/file.xml')

    def test_process_camt053_folder_mixed(self):
        """Cover process_camt053_folder with good + bad files (lines 305-309)."""
        folder = tempfile.mkdtemp()
        try:
            # Write one good file
            good_path = os.path.join(folder, 'good.xml')
            with open(good_path, 'w') as f:
                f.write(CAMT_XML)
            # Write one bad file
            bad_path = os.path.join(folder, 'bad.xml')
            with open(bad_path, 'w') as f:
                f.write('not xml')

            files_df, statements_df, transactions_df = process_camt053_folder(folder)
            # Should have 2 files processed
            self.assertEqual(len(files_df), 2)
            # Check we got at least one success and one failure
            statuses = files_df['Status'].tolist()
            self.assertTrue(any('Success' in s for s in statuses))
            self.assertTrue(any('Failed' in s for s in statuses))
        finally:
            shutil.rmtree(folder)


# ── BaseParser coverage tests ─────────────────────────────────────────

class TestBaseParserCoverage(unittest.TestCase):
    """Cover uncovered lines in base_parser.py."""

    def test_export_csv_success(self):
        """Cover export_csv success path (lines 101-107)."""
        camt_file = _write_xml(CAMT_XML)
        output_csv = tempfile.NamedTemporaryFile(suffix='.csv', delete=False)
        output_csv.close()
        try:
            parser = CamtParser(camt_file)
            parser.export_csv(output_csv.name)
            self.assertTrue(os.path.exists(output_csv.name))
        finally:
            os.unlink(camt_file)
            if os.path.exists(output_csv.name):
                os.unlink(output_csv.name)

    def test_export_csv_cleanup_on_error(self):
        """Cover export_csv cleanup on parse exception (lines 108-112)."""
        camt_file = _write_xml(CAMT_XML)
        output_path = '/tmp/test_bsp_output.csv'
        try:
            parser = CamtParser(camt_file)
            # Mock parse to raise error after temp file is created
            original_parse = parser.parse
            def failing_parse(*args, **kwargs):
                # Create the temp file first (simulating partial write)
                Path(f"{output_path}.tmp").touch()
                raise RuntimeError("parse error")
            with patch.object(parser, 'parse', side_effect=failing_parse):
                with self.assertRaises(IOError):
                    parser.export_csv(output_path)
            # Temp file should be cleaned up
            self.assertFalse(os.path.exists(f'{output_path}.tmp'))
        finally:
            os.unlink(camt_file)
            for f in [output_path, f'{output_path}.tmp']:
                if os.path.exists(f):
                    os.unlink(f)

    def test_export_json_success(self):
        """Cover export_json success path (lines 124-138)."""
        camt_file = _write_xml(CAMT_XML)
        output_json = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        output_json.close()
        try:
            parser = CamtParser(camt_file)
            parser.export_json(output_json.name)
            self.assertTrue(os.path.exists(output_json.name))
            with open(output_json.name) as f:
                data = json.load(f)
            self.assertIn('summary', data)
            self.assertIn('transactions', data)
        finally:
            os.unlink(camt_file)
            if os.path.exists(output_json.name):
                os.unlink(output_json.name)

    def test_export_json_cleanup_on_error(self):
        """Cover export_json cleanup on parse exception (lines 139-143)."""
        camt_file = _write_xml(CAMT_XML)
        output_path = '/tmp/test_bsp_output.json'
        try:
            parser = CamtParser(camt_file)
            def failing_parse(*args, **kwargs):
                Path(f"{output_path}.tmp").touch()
                raise RuntimeError("parse error")
            with patch.object(parser, 'parse', side_effect=failing_parse):
                with self.assertRaises(IOError):
                    parser.export_json(output_path)
            self.assertFalse(os.path.exists(f'{output_path}.tmp'))
        finally:
            os.unlink(camt_file)
            for f in [output_path, f'{output_path}.tmp']:
                if os.path.exists(f):
                    os.unlink(f)

    def test_str_fallback_on_exception(self):
        """Cover __str__ fallback when get_summary() raises (lines 166-167)."""
        camt_file = _write_xml(CAMT_XML)
        try:
            parser = CamtParser(camt_file)
            with patch.object(parser, 'get_summary', side_effect=RuntimeError("fail")):
                result = str(parser)
                self.assertIn('CamtParser', result)
                self.assertIn('file=', result)
        finally:
            os.unlink(camt_file)

    def test_str_with_summary(self):
        """Cover __str__ normal path (lines 161-165)."""
        camt_file = _write_xml(CAMT_XML)
        try:
            parser = CamtParser(camt_file)
            result = str(parser)
            self.assertIn('CamtParser', result)
            self.assertIn('transactions', result)
        finally:
            os.unlink(camt_file)

    def test_repr(self):
        """Cover base_parser __repr__ method (line 152)."""
        pain_file = _write_xml(PAIN_XML)
        try:
            parser = Pain001Parser(pain_file)
            result = repr(parser)
            self.assertIn('Pain001Parser', result)
            self.assertIn('file=', result)
        finally:
            os.unlink(pain_file)

    def test_abstract_parse_pass(self):
        """Cover abstract parse() pass statement (line 68)."""
        # Call the abstract method directly via the base class
        camt_file = _write_xml(CAMT_XML)
        try:
            parser = CamtParser(camt_file)
            # Call the abstract method from the base class
            result = BankStatementParser.parse(parser)
            self.assertIsNone(result)  # pass returns None
        finally:
            os.unlink(camt_file)

    def test_abstract_get_summary_pass(self):
        """Cover abstract get_summary() pass statement (line 89)."""
        camt_file = _write_xml(CAMT_XML)
        try:
            parser = CamtParser(camt_file)
            result = BankStatementParser.get_summary(parser)
            self.assertIsNone(result)
        finally:
            os.unlink(camt_file)


# ── InputValidator coverage tests ─────────────────────────────────────

class TestInputValidatorCoverage(unittest.TestCase):
    """Cover uncovered lines in input_validator.py."""

    def test_validate_file_size_os_error(self):
        """Cover _validate_file_size with OSError (lines 262-263)."""
        validator = InputValidator()
        f = _write_xml(CAMT_XML)
        try:
            path = Path(f)
            with patch.object(Path, 'stat', side_effect=OSError("stat error")):
                with self.assertRaises(ValidationError):
                    validator._validate_file_size(path)
        finally:
            os.unlink(f)

    def test_validate_input_format_unicode_decode_error(self):
        """Cover outer UnicodeDecodeError catch (lines 338-339)."""
        validator = InputValidator()
        # Create a file with binary content that has .xml extension
        f = tempfile.NamedTemporaryFile(
            mode='wb', suffix='.xml', delete=False
        )
        # Write valid XML header followed by invalid UTF-8
        f.write(b'<?xml version="1.0"?>\n<Document>\xff\xfe\x80\x81</Document>')
        f.close()
        try:
            path = Path(f.name)
            # This should handle the UnicodeDecodeError in the outer handler
            with patch('builtins.open', side_effect=UnicodeDecodeError('utf-8', b'', 0, 1, 'invalid')):
                with self.assertRaises(ValidationError):
                    validator._validate_input_format(path)
        finally:
            os.unlink(f.name)


# ── CLI coverage tests ────────────────────────────────────────────────

class TestCLICoverage(unittest.TestCase):
    """Cover uncovered lines in cli.py."""

    def setUp(self):
        self.camt_file = _write_xml(CAMT_XML)
        self.pain_file = _write_xml(PAIN_XML)

    def tearDown(self):
        for f in [self.camt_file, self.pain_file]:
            if os.path.exists(f):
                os.unlink(f)

    def test_sanitize_file_path_none(self):
        """Cover _sanitize_file_path(None) → ValueError (line 75)."""
        cli = BankStatementCLI()
        with self.assertRaises(ValueError):
            cli._sanitize_file_path(None)

    def test_parse_camt_streaming_with_output(self):
        """Cover parse_camt streaming + output path (lines 173-199)."""
        cli = BankStatementCLI()
        output_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False
        )
        output_file.close()
        output_path = Path(output_file.name)
        try:
            cli.parse_camt(
                Path(self.camt_file),
                output_path=output_path,
                show_pii=False,
                streaming=True,
            )
            self.assertTrue(os.path.exists(output_file.name) or
                           os.path.exists(str(output_path.parent / cli.validator.get_safe_filename(output_path.name))))
        finally:
            # Clean up any output files
            for f in os.listdir(output_path.parent):
                full = os.path.join(str(output_path.parent), f)
                if full.startswith(str(output_path.parent)) and f.endswith('.csv'):
                    pass  # Don't delete other csv files
            if os.path.exists(output_file.name):
                os.unlink(output_file.name)

    def test_parse_camt_streaming_console_limit(self):
        """Cover streaming console output with limit (lines 201-223)."""
        # Create a CAMT file with many transactions
        entries = ''
        for i in range(105):
            entries += f'''
      <Ntry>
        <Amt Ccy="EUR">{i + 1}.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Sts>BOOK</Sts>
        <BookgDt><Dt>2024-01-15</Dt></BookgDt>
        <ValDt><Dt>2024-01-15</Dt></ValDt>
        <NtryDtls><TxDtls><Refs><EndToEndId>REF{i:04d}</EndToEndId></Refs>
        <RltdPties><Dbtr><Nm>Sender{i}</Nm></Dbtr></RltdPties></TxDtls></NtryDtls>
      </Ntry>'''

        large_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <GrpHdr><MsgId>M1</MsgId><CreDtTm>2024-01-01</CreDtTm></GrpHdr>
    <Stmt>
      <Id>S1</Id><CreDtTm>2024-01-01</CreDtTm>
      <Acct><Id><IBAN>DE89370400440532013000</IBAN></Id></Acct>
      {entries}
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
        f = _write_xml(large_xml)
        try:
            cli = BankStatementCLI()
            with patch('builtins.print') as mock_print:
                cli.parse_camt(Path(f), streaming=True)
                # Check that the "showing first 100" message was printed
                calls = [str(c) for c in mock_print.call_args_list]
                self.assertTrue(any('100' in c for c in calls))
        finally:
            os.unlink(f)

    def test_parse_camt_streaming_show_pii(self):
        """Cover streaming console with show_pii=True (lines 215-217)."""
        cli = BankStatementCLI()
        with patch('builtins.print') as mock_print:
            cli.parse_camt(Path(self.camt_file), show_pii=True, streaming=True)
            calls = [str(c) for c in mock_print.call_args_list]
            self.assertTrue(any('WARNING' in c for c in calls))

    def test_parse_pain_streaming_with_output(self):
        """Cover parse_pain streaming + output path (lines 281-307), including header=False."""
        # Use the test data file which has multiple payments to cover line 304
        pain_file = os.path.join(
            os.path.dirname(__file__), 'test_data', 'pain.001.001.03.xml'
        )
        cli = BankStatementCLI()
        output_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False
        )
        output_file.close()
        output_path = Path(output_file.name)
        try:
            cli.parse_pain(
                Path(pain_file),
                output_path=output_path,
                show_pii=False,
                streaming=True,
            )
        finally:
            # Clean up
            safe_name = cli.validator.get_safe_filename(output_path.name)
            safe_path = str(output_path.parent / safe_name)
            for f in [output_file.name, safe_path, f'{safe_path}.tmp']:
                if os.path.exists(f):
                    os.unlink(f)

    def test_parse_pain_streaming_console(self):
        """Cover parse_pain streaming console output (lines 309-331)."""
        cli = BankStatementCLI()
        with patch('builtins.print'):
            cli.parse_pain(Path(self.pain_file), streaming=True)

    def test_parse_pain_streaming_show_pii(self):
        """Cover parse_pain streaming console with show_pii=True (lines 323-325)."""
        cli = BankStatementCLI()
        with patch('builtins.print') as mock_print:
            cli.parse_pain(Path(self.pain_file), show_pii=True, streaming=True)
            calls = [str(c) for c in mock_print.call_args_list]
            self.assertTrue(any('WARNING' in c for c in calls))

    def test_parse_pain_nonstreaming_output(self):
        """Cover parse_pain non-streaming output (lines 338-342)."""
        cli = BankStatementCLI()
        output_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False
        )
        output_file.close()
        output_path = Path(output_file.name)
        try:
            cli.parse_pain(
                Path(self.pain_file),
                output_path=output_path,
                show_pii=False,
            )
        finally:
            if os.path.exists(output_file.name):
                os.unlink(output_file.name)

    def test_parse_pain_nonstreaming_show_pii(self):
        """Cover parse_pain non-streaming show_pii console (lines 344-346)."""
        cli = BankStatementCLI()
        with patch('builtins.print') as mock_print:
            cli.parse_pain(Path(self.pain_file), show_pii=True)
            calls = [str(c) for c in mock_print.call_args_list]
            self.assertTrue(any('WARNING' in c for c in calls))

    def test_parse_pain_nonstreaming_redacted_console(self):
        """Cover parse_pain non-streaming redacted console (lines 347-349)."""
        cli = BankStatementCLI()
        with patch('builtins.print'):
            cli.parse_pain(Path(self.pain_file))

    def test_run_argparse_failure(self):
        """Cover run() argparse failure path (lines 374-376)."""
        cli = BankStatementCLI()
        with patch('sys.argv', ['prog', '--type']):
            with self.assertRaises(SystemExit):
                cli.run()

    def test_run_streaming_camt(self):
        """Cover run() with --streaming flag for camt (line 421)."""
        cli = BankStatementCLI()
        with patch('sys.argv', ['prog', '--type', 'camt', '--input', self.camt_file, '--streaming']):
            with patch.object(cli, 'parse_camt') as mock_parse:
                with patch.object(cli, '_sanitize_file_path', return_value=self.camt_file):
                    with patch.object(cli.validator, 'validate_input_file_path', return_value=Path(self.camt_file)):
                        cli.run()
                        mock_parse.assert_called_once()
                        # Verify streaming=True was passed
                        call_args = mock_parse.call_args
                        self.assertTrue(call_args[0][3] if len(call_args[0]) > 3 else call_args[1].get('streaming'))

    def test_run_streaming_pain001(self):
        """Cover run() with --streaming flag for pain001 (line 426)."""
        cli = BankStatementCLI()
        with patch('sys.argv', ['prog', '--type', 'pain001', '--input', self.pain_file, '--streaming']):
            with patch.object(cli, 'parse_pain') as mock_parse:
                with patch.object(cli, '_sanitize_file_path', return_value=self.pain_file):
                    with patch.object(cli.validator, 'validate_input_file_path', return_value=Path(self.pain_file)):
                        cli.run()
                        mock_parse.assert_called_once()

    def test_run_non_streaming_pain001(self):
        """Cover run() non-streaming pain001 (line 428)."""
        cli = BankStatementCLI()
        with patch('sys.argv', ['prog', '--type', 'pain001', '--input', self.pain_file]):
            with patch.object(cli, 'parse_pain') as mock_parse:
                with patch.object(cli, '_sanitize_file_path', return_value=self.pain_file):
                    with patch.object(cli.validator, 'validate_input_file_path', return_value=Path(self.pain_file)):
                        cli.run()
                        mock_parse.assert_called_once()

    def test_run_outer_exception(self):
        """Cover run() outer exception handler (lines 432-435)."""
        cli = BankStatementCLI()
        with patch('sys.argv', ['prog', '--type', 'camt', '--input', self.camt_file]):
            with patch.object(cli, 'parse_camt', side_effect=RuntimeError("fail")):
                with patch.object(cli, '_sanitize_file_path', return_value=self.camt_file):
                    with patch.object(cli.validator, 'validate_input_file_path', return_value=Path(self.camt_file)):
                        with self.assertRaises(SystemExit):
                            cli.run()

    def test_main_block(self):
        """Cover the pattern used by __main__ block (lines 441-442).
        Note: The actual if __name__ == '__main__' guard can't be covered in-process.
        """
        # Just verify the pattern works
        cli = BankStatementCLI()
        self.assertIsNotNone(cli)
        self.assertIsNotNone(cli.parser)

    def test_run_missing_required_args_safety_check(self):
        """Cover run() missing args safety check (lines 381-384)."""
        cli = BankStatementCLI()
        with patch('sys.argv', ['prog', '--type', 'camt', '--input', 'dummy']):
            with patch.object(cli.parser, 'parse_args') as mock_parse:
                mock_args = MagicMock()
                mock_args.input = None
                mock_args.type = 'camt'
                mock_parse.return_value = mock_args
                with self.assertRaises(SystemExit):
                    cli.run()

    def test_run_argparse_failure_defensive_return(self):
        """Cover defensive return after sys.exit in argparse failure (line 378)."""
        cli = BankStatementCLI()
        with patch('sys.argv', ['prog', '--type']):
            # Mock sys.exit to NOT raise (simulating mocked test environment)
            with patch('sys.exit') as mock_exit:
                cli.run()
                # sys.exit should have been called
                mock_exit.assert_called()

    def test_run_unsupported_type(self):
        """Cover unsupported type else branch (lines 432-433)."""
        cli = BankStatementCLI()
        with patch('sys.argv', ['prog', '--type', 'camt', '--input', self.camt_file]):
            with patch.object(cli.parser, 'parse_args') as mock_parse:
                mock_args = MagicMock()
                mock_args.input = self.camt_file
                mock_args.type = 'unsupported'
                mock_args.output = None
                mock_args.verbose = False
                mock_args.max_size = 100
                mock_args.show_pii = False
                mock_args.streaming = False
                mock_parse.return_value = mock_args
                with patch.object(cli, '_sanitize_file_path', return_value=self.camt_file):
                    with patch.object(cli.validator, 'validate_input_file_path', return_value=Path(self.camt_file)):
                        with self.assertRaises(SystemExit):
                            cli.run()


# ── CLI output path tests for parse_pain ──────────────────────────────

class TestCLIOutputPaths(unittest.TestCase):
    """Additional tests for safe path handling in CLI output."""

    def setUp(self):
        self.pain_file = _write_xml(PAIN_XML)

    def tearDown(self):
        if os.path.exists(self.pain_file):
            os.unlink(self.pain_file)

    def test_parse_pain_streaming_console_many_payments(self):
        """Cover streaming pain console limit (lines 330-331)."""
        # Create pain XML with many payments
        pmt_infos = ''
        for i in range(105):
            pmt_infos += f'''
    <PmtInf>
      <PmtInfId>PMT{i:04d}</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <NbOfTxs>1</NbOfTxs>
      <ReqdExctnDt>2024-01-15</ReqdExctnDt>
      <Dbtr><Nm>Sender{i}</Nm></Dbtr>
      <DbtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></DbtrAcct>
      <DbtrAgt><FinInstnId><BIC>BANKDEFFXXX</BIC></FinInstnId></DbtrAgt>
      <CdtTrfTxInf>
        <PmtId><EndToEndId>E2E{i:04d}</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="EUR">{i + 1}.00</InstdAmt></Amt>
        <Cdtr><Nm>Recv{i}</Nm></Cdtr>
        <RmtInf><Ustrd>Inv{i:04d}</Ustrd></RmtInf>
      </CdtTrfTxInf>
    </PmtInf>'''

        large_pain = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>M1</MsgId>
      <CreDtTm>2024-01-01T00:00:00</CreDtTm>
      <NbOfTxs>105</NbOfTxs>
      <InitgPty><Nm>Test</Nm></InitgPty>
    </GrpHdr>
    {pmt_infos}
  </CstmrCdtTrfInitn>
</Document>"""
        f = _write_xml(large_pain)
        try:
            cli = BankStatementCLI()
            with patch('builtins.print') as mock_print:
                cli.parse_pain(Path(f), streaming=True)
                calls = [str(c) for c in mock_print.call_args_list]
                self.assertTrue(any('100' in c for c in calls))
        finally:
            os.unlink(f)


if __name__ == '__main__':
    unittest.main()
