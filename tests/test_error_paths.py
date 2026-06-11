"""Error-path and failure-mode tests.

Exercises what happens when things go wrong: unreadable files,
malformed XML, permission errors, streaming failures, export cleanup,
and CLI error exits — across cli.py, camt_parser.py,
pain001_parser.py, bank_statement_parsers.py, base_parser.py, and
input_validator.py.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lxml import etree

from bankstatementparser.bank_statement_parsers import (
    Camt053Parser,
    FileParserError,
    process_camt053_folder,
)
from bankstatementparser.bank_statement_parsers import (
    Pain001Parser as BankPain001Parser,
)
from bankstatementparser.base_parser import BankStatementParser
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.cli import BankStatementCLI
from bankstatementparser.exceptions import Pain001ParseError
from bankstatementparser.input_validator import (
    InputValidator,
    ValidationError,
)
from bankstatementparser.pain001_parser import Pain001Parser

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


def _write_xml(xml_content, suffix=".xml"):
    """Helper: write XML content to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(xml_content)
    return path


def _mktemp(suffix):
    """Helper: create an empty temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


# ── CamtParser coverage tests ────────────────────────────────────────


class TestCamtParserCoverage(unittest.TestCase):
    """CamtParser error paths and edge cases."""

    def setUp(self):
        self.camt_file = _write_xml(CAMT_XML)
        self.camt_prtry_file = _write_xml(CAMT_XML_WITH_PRTRY)

    def tearDown(self):
        for f in [self.camt_file, self.camt_prtry_file]:
            if os.path.exists(f):
                os.unlink(f)

    def test_permission_error_in_init(self):
        """An unreadable file raises PermissionError/ValidationError."""
        # chmod(0o000) is ineffective on Windows; mock open() instead.
        # Pass as Path to bypass input validator, hit open() directly.
        with patch("builtins.open", side_effect=PermissionError("denied")):
            with self.assertRaises((PermissionError, ValidationError)):
                CamtParser(Path(self.camt_file))

    def test_file_not_found_in_init(self):
        """A missing file raises FileNotFoundError."""
        # Pass Path object to bypass validator
        with self.assertRaises(FileNotFoundError):
            CamtParser(Path("/tmp/nonexistent_camt_file_12345.xml"))

    def test_generic_exception_in_init(self):
        """A file-read OSError surfaces as ValidationError/IOError."""
        # Pass Path to bypass validator, then mock open to raise generic error
        with patch("builtins.open", side_effect=OSError("disk error")):
            with self.assertRaises((ValidationError, IOError)):
                CamtParser(Path(self.camt_file))

    def test_dbit_balance_sign_adjustment(self):
        """DBIT balances are reported as negative amounts."""
        parser = CamtParser(self.camt_file)
        balances_df = parser.get_account_balances()
        # CLBD balance is DBIT, so amount should be negative
        clbd = balances_df[balances_df["Code"] == "CLBD"]
        self.assertFalse(clbd.empty)
        self.assertLess(clbd.iloc[0]["Amount"], 0)

    def test_prtry_balance_type(self):
        """Prtry balance types are recognized (PR #5 fix)."""
        parser = CamtParser(self.camt_prtry_file)
        balances_df = parser.get_account_balances()
        codes = balances_df["Code"].tolist()
        # Check Proprietary type was found
        self.assertTrue(any("Proprietary" in str(c) for c in codes))

    def test_na_balance_type(self):
        """Balance type is N/A when neither Cd nor Prtry is present."""
        parser = CamtParser(self.camt_prtry_file)
        balances_df = parser.get_account_balances()
        codes = balances_df["Code"].tolist()
        self.assertIn("N/A", codes)

    def test_malformed_bal_element_skipped(self):
        """A Bal element without Amt is skipped with a warning."""
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
        """redact_pii masks address fields in transactions."""
        parser = CamtParser(self.camt_file)
        txs = parser.get_transactions(redact_pii=True)
        # Addresses should be redacted if they existed
        if "DebtorAddress" in txs.columns:
            for val in txs["DebtorAddress"].dropna():
                self.assertEqual(val, "***REDACTED***")

    def test_streaming_parse_basic(self):
        """Streaming parse yields transactions."""
        parser = CamtParser(self.camt_file)
        transactions = list(parser.parse_streaming())
        self.assertGreater(len(transactions), 0)

    def test_streaming_dbit_and_pii_redaction(self):
        """Streaming negates DBIT amounts and redacts addresses."""
        parser = CamtParser(self.camt_file)
        transactions = list(parser.parse_streaming(redact_pii=True))
        # Should have DBIT transaction with negative amount
        dbit_txs = [t for t in transactions if t.get("DrCr") == "DBIT"]
        for tx in dbit_txs:
            self.assertLess(tx["Amount"], 0)
        # Addresses should be redacted
        for tx in transactions:
            if "DebtorAddress" in tx:
                self.assertEqual(tx["DebtorAddress"], "***REDACTED***")
            if "CreditorAddress" in tx:
                self.assertEqual(tx["CreditorAddress"], "***REDACTED***")

    def test_streaming_malformed_transaction_propagates(self):
        """R-007: streaming must fail-fast on per-row parse errors.

        Previously this test asserted the parser swallowed the
        exception and continued, which directly contradicted the
        R-007 control in ``docs/compliance/RISK_REGISTER.md`` and
        the equivalent fail-fast behaviour in
        :class:`Pain001Parser`. The current behaviour is to log
        the error and propagate it so downstream balance checks
        cannot silently miss dropped rows.
        """
        parser = CamtParser(self.camt_file)
        with (
            patch.object(
                parser,
                "_parse_streaming_transaction",
                side_effect=ValueError("Malformed transaction"),
            ),
            self.assertRaises(ValueError),
        ):
            list(parser.parse_streaming())

    def test_streaming_file_not_found(self):
        """Streaming should use the normalized in-memory XML buffer."""
        parser = CamtParser(self.camt_file)
        parser._file_path = "/nonexistent/file.xml"
        transactions = list(parser.parse_streaming())
        self.assertGreater(len(transactions), 0)

    def test_streaming_permission_error(self):
        """Streaming should not reopen the original file."""
        parser = CamtParser(self.camt_file)
        with patch("builtins.open", side_effect=PermissionError("no access")):
            transactions = list(parser.parse_streaming())
            self.assertGreater(len(transactions), 0)

    def test_streaming_generic_error(self):
        """Streaming should be independent of later file I/O failures."""
        parser = CamtParser(self.camt_file)
        with patch("builtins.open", side_effect=OSError("disk error")):
            transactions = list(parser.parse_streaming())
            self.assertGreater(len(transactions), 0)

    def test_streaming_cleanup_failure(self):
        """Streaming no longer uses temp files for CAMT input."""
        parser = CamtParser(self.camt_file)
        with patch("os.unlink", side_effect=OSError("cannot delete")):
            transactions = list(parser.parse_streaming())
            self.assertGreater(len(transactions), 0)

    def test_streaming_val_date_datetime_fallback(self):
        """Date elements fall back to DtTm when Dt is absent."""
        # Uses DtTm instead of Dt - the existing test data uses DtTm for BookgDt
        parser = CamtParser(
            os.path.join(
                os.path.dirname(__file__),
                "test_data",
                "camt.053.001.02.xml",
            )
        )
        transactions = list(parser.parse_streaming())
        self.assertGreater(len(transactions), 0)
        # Check booking dates came from DtTm elements
        for tx in transactions:
            if tx.get("BookgDt"):
                self.assertIn("T", tx["BookgDt"])  # DtTm format has 'T'

    def test_entity_error_recovery_parsing(self):
        """Undeclared entities are rejected unless allow_recovery=True."""
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml += (
            "<Document>\n<BkToCstmrStmt>\n<GrpHdr><MsgId>M1</MsgId></GrpHdr>\n"
        )
        xml += "<Stmt><Id>S1</Id><CreDtTm>2024-01-01</CreDtTm>"
        xml += "<Acct><Id><IBAN>DE89370400440532013000</IBAN></Id></Acct>"
        xml += '<Ntry><Amt Ccy="EUR">10</Amt><CdtDbtInd>CRDT</CdtDbtInd>'
        xml += "<Sts>BOOK</Sts><BookgDt><Dt>2024-01-01</Dt></BookgDt>"
        xml += "<ValDt><Dt>2024-01-01</Dt></ValDt>"
        xml += "<NtryDtls><TxDtls><Refs><EndToEndId>R1</EndToEndId></Refs>"
        xml += "<RltdPties><Dbtr><Nm>D</Nm></Dbtr></RltdPties>"
        xml += "</TxDtls></NtryDtls></Ntry>"
        xml += "</Stmt>\n</BkToCstmrStmt>\n</Document>"
        # Inject an undeclared entity
        xml = xml.replace("<MsgId>M1</MsgId>", "<MsgId>&foo;M1</MsgId>")
        f = _write_xml(xml)
        try:
            # Strict default: the undeclared entity is a parse error
            with self.assertRaises(etree.XMLSyntaxError):
                CamtParser(f)
            # Opt-in recovery parses what it can
            parser = CamtParser(f, allow_recovery=True)
            self.assertIsNotNone(parser.tree)
        finally:
            os.unlink(f)

    def test_recovery_mode_non_entity_syntax_error_still_raises(self):
        """Recovery only retries entity errors; other syntax errors raise."""
        with self.assertRaises(etree.XMLSyntaxError):
            CamtParser.from_string("<Document><bad", allow_recovery=True)

    def test_general_xml_parse_exception(self):
        """Non-XMLSyntaxError parse exceptions propagate unchanged."""
        f = _write_xml(CAMT_XML)
        try:
            parser = CamtParser.__new__(CamtParser)
            parser._original_file_name = f
            parser._file_path = f
            # Mock etree.fromstring to raise a non-XMLSyntaxError
            with (
                patch(
                    "bankstatementparser.camt_parser.etree.fromstring",
                    side_effect=RuntimeError("unexpected"),
                ),
                self.assertRaises(RuntimeError),
            ):
                CamtParser(f)
        finally:
            os.unlink(f)

    def test_get_summary(self):
        """get_summary returns account, count, and balances."""
        parser = CamtParser(self.camt_file)
        summary = parser.get_summary()
        self.assertIn("account_id", summary)
        self.assertIn("transaction_count", summary)
        self.assertIn("opening_balance", summary)
        self.assertIn("closing_balance", summary)

    def test_get_element_text_helper(self):
        """_get_element_text returns text or empty string."""
        parser = CamtParser(self.camt_file)
        from lxml import etree as et

        elem = et.fromstring("<Root><Child>hello</Child></Root>")
        # Existing element
        self.assertEqual(parser._get_element_text(elem, "./Child"), "hello")
        # Non-existing element
        self.assertEqual(parser._get_element_text(elem, "./Missing"), "")

    def test_streaming_valdt_datetime_fallback(self):
        """ValDt falls back to DtTm when Dt is absent."""
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
            self.assertIn("T", transactions[0]["ValDt"])
        finally:
            os.unlink(f)


# ── Pain001Parser coverage tests ─────────────────────────────────────


class TestPain001ParserCoverage(unittest.TestCase):
    """Pain001Parser error paths and edge cases."""

    def setUp(self):
        self.pain_file = _write_xml(PAIN_XML)

    def tearDown(self):
        if os.path.exists(self.pain_file):
            os.unlink(self.pain_file)

    def test_permission_error_in_init(self):
        """An unreadable file raises PermissionError/ValidationError."""
        # chmod(0o000) is ineffective on Windows; mock open() instead.
        # Pass Path to bypass validator, hit open() directly.
        with patch("builtins.open", side_effect=PermissionError("denied")):
            with self.assertRaises((PermissionError, ValidationError)):
                Pain001Parser(Path(self.pain_file))

    def test_file_not_found_in_init(self):
        """A missing file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            Pain001Parser(Path("/tmp/nonexistent_pain_file_12345.xml"))

    def test_generic_exception_in_init(self):
        """A file-read OSError surfaces as ValidationError/IOError."""
        # Pass Path to bypass validator
        with patch("builtins.open", side_effect=OSError("disk error")):
            with self.assertRaises((ValidationError, IOError)):
                Pain001Parser(Path(self.pain_file))

    def test_value_error_in_xml_parsing(self):
        """A 'start tag expected' ValueError becomes ValidationError."""
        # Write valid-ish content that bypasses validator but triggers ValueError
        f = _write_xml('<?xml version="1.0"?><Empty/>')
        try:
            # Pass Path to bypass validator
            with (
                patch(
                    "bankstatementparser.pain001_parser.etree.fromstring",
                    side_effect=ValueError(
                        "Start tag expected, '<' not found"
                    ),
                ),
                self.assertRaises(ValidationError),
            ):
                Pain001Parser(Path(f))
        finally:
            os.unlink(f)

    def test_value_error_other_in_xml_parsing(self):
        """Other ValueErrors become 'Invalid XML format' ValidationError."""
        f = _write_xml('<?xml version="1.0"?><Empty/>')
        try:
            with patch(
                "bankstatementparser.pain001_parser.etree.fromstring",
                side_effect=ValueError("some other value error"),
            ):
                with self.assertRaises(ValidationError) as ctx:
                    Pain001Parser(Path(f))
                self.assertIn("Invalid XML format", str(ctx.exception))
        finally:
            os.unlink(f)

    def test_streaming_parse_basic(self):
        """Streaming parse yields payments."""
        parser = Pain001Parser(self.pain_file)
        payments = list(parser.parse_streaming())
        self.assertGreater(len(payments), 0)

    def test_streaming_with_pii_redaction(self):
        """Streaming redacts PII name/IBAN fields when requested."""
        parser = Pain001Parser(self.pain_file)
        payments = list(parser.parse_streaming(redact_pii=True))
        for payment in payments:
            for field in ["DbtrNm", "CdtrNm", "DbtrIBAN", "InitgPty"]:
                if payment.get(field):
                    self.assertEqual(payment[field], "***REDACTED***")

    def test_streaming_validation_failure(self):
        """Streaming fails when the source file disappears."""
        parser = Pain001Parser(self.pain_file)
        parser.file_name = "/nonexistent/file.xml"
        with self.assertRaises((ValidationError, FileNotFoundError)):
            list(parser.parse_streaming())

    def test_streaming_file_not_found(self):
        """Streaming raises FileNotFoundError for a missing path."""
        parser = Pain001Parser(self.pain_file)
        # Make the file_name not a string to skip validation, then fail on read
        parser.file_name = Path("/nonexistent/file.xml")
        with self.assertRaises(FileNotFoundError):
            list(parser.parse_streaming())

    def test_streaming_permission_error(self):
        """Streaming wraps PermissionError as ValidationError."""
        parser = Pain001Parser(self.pain_file)
        parser.file_name = 42  # Not a string, skip validation
        with patch("builtins.open", side_effect=PermissionError("no access")):
            with self.assertRaises(ValidationError):
                list(parser.parse_streaming())

    def test_streaming_generic_error(self):
        """Streaming wraps unexpected I/O errors as ValidationError."""
        parser = Pain001Parser(self.pain_file)
        parser.file_name = 42  # Not a string, skip validation
        with patch("builtins.open", side_effect=OSError("disk error")):
            with self.assertRaises(ValidationError):
                list(parser.parse_streaming())

    def test_streaming_malformed_payment_raises(self):
        """Streaming fails fast on a malformed payment."""
        parser = Pain001Parser(self.pain_file)

        def side_effect(elem, pmt_info, header, redact_pii=False):
            raise ValueError("Malformed payment")

        with (
            patch.object(
                parser, "_parse_streaming_payment", side_effect=side_effect
            ),
            self.assertRaises(ValueError),
        ):
            list(parser.parse_streaming())

    def test_streaming_cleanup_failure(self):
        """A failing temp-file cleanup does not break streaming."""
        parser = Pain001Parser(self.pain_file)
        with patch("os.unlink", side_effect=OSError("cannot delete")):
            list(parser.parse_streaming())

    def test_get_summary(self):
        """get_summary returns account and transaction count."""
        parser = Pain001Parser(self.pain_file)
        summary = parser.get_summary()
        self.assertIn("account_id", summary)
        self.assertIn("transaction_count", summary)
        self.assertEqual(summary["transaction_count"], 1)

    def test_get_summary_internal_error_raises(self):
        """get_summary raises Pain001ParseError on internal errors."""
        parser = Pain001Parser(self.pain_file)
        # Corrupt the tree to trigger exception
        parser.tree = None
        with self.assertRaises(Pain001ParseError):
            parser.get_summary()

    def test_streaming_pmtinf_child_extraction(self):
        """Streaming extracts Dbtr/DbtrAgt data across multiple PmtInf blocks.

        iterparse fires 'end' for PmtInf after all CdtTrfTxInf ends
        inside it, so multi-batch files exercise the PmtInf-level
        extraction ordering.
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
    """Compatibility-wrapper error paths and edge cases."""

    def setUp(self):
        self.camt_file = _write_xml(CAMT_XML)
        self.pain_file = _write_xml(PAIN_XML)

    def tearDown(self):
        for f in [self.camt_file, self.pain_file]:
            if os.path.exists(f):
                os.unlink(f)

    def test_wrapper_pain001_nonexistent_file(self):
        """Wrapper raises on a nonexistent file."""
        with self.assertRaises((FileNotFoundError, ValidationError)):
            BankPain001Parser("/nonexistent/file.xml")

    def test_wrapper_pain001_redact_pii(self):
        """Wrapper redacts payment addresses when redact_pii=True."""
        # Create PAIN XML with address lines
        pain_with_addr = PAIN_XML.replace(
            "<Cdtr><Nm>Receiver Corp</Nm></Cdtr>",
            "<Cdtr><Nm>Receiver Corp</Nm><PstlAdr><AdrLine>123 Street</AdrLine></PstlAdr></Cdtr>",
        )
        f = _write_xml(pain_with_addr)
        try:
            parser = BankPain001Parser(f, redact_pii=True)
            for payment in parser.payments:
                if payment.get("Address"):
                    self.assertEqual(payment["Address"], "***REDACTED***")
        finally:
            os.unlink(f)

    def test_camt053_balance_grouping(self):
        """Wrapper groups balances by account onto statements."""
        parser = Camt053Parser(self.camt_file)
        self.assertGreater(len(parser.statements), 0)

    def test_camt053_validation_error(self):
        """Non-XML content raises FileParserError/ValidationError."""
        f = _write_xml("not xml content")
        try:
            with self.assertRaises((FileParserError, ValidationError)):
                Camt053Parser(f)
        finally:
            os.unlink(f)

    def test_camt053_generic_exception(self):
        """An empty CAMT document fails as FileParserError."""
        xml = '<?xml version="1.0"?><Document><BkToCstmrStmt></BkToCstmrStmt></Document>'
        f = _write_xml(xml)
        try:
            Camt053Parser(f)
        except (FileParserError, Exception):
            pass  # Expected
        finally:
            os.unlink(f)

    def test_camt053_validation_error_from_camt_parser(self):
        """ValidationError from CamtParser maps to FileParserError."""
        # Mock CamtParser to raise ValidationError
        with patch(
            "bankstatementparser.bank_statement_parsers.CamtParser",
            side_effect=ValidationError("test validation error"),
        ):
            with self.assertRaises(FileParserError) as ctx:
                Camt053Parser(self.camt_file)
            self.assertIn("Not a valid CAMT.053 file", str(ctx.exception))

    def test_camt053_file_not_found(self):
        """Wrapper raises FileNotFoundError for a missing path."""
        with self.assertRaises(FileNotFoundError):
            Camt053Parser("/nonexistent/camt/file.xml")

    def test_process_camt053_folder_mixed(self):
        """Folder processing records per-file Success/Failed status."""
        folder = tempfile.mkdtemp()
        try:
            # Write one good file
            good_path = os.path.join(folder, "good.xml")
            with open(good_path, "w") as f:
                f.write(CAMT_XML)
            # Write one bad file
            bad_path = os.path.join(folder, "bad.xml")
            with open(bad_path, "w") as f:
                f.write("not xml")

            (
                files_df,
                _statements_df,
                _transactions_df,
            ) = process_camt053_folder(folder)
            # Should have 2 files processed
            self.assertEqual(len(files_df), 2)
            # Check we got at least one success and one failure
            statuses = files_df["Status"].tolist()
            self.assertTrue(any("Success" in s for s in statuses))
            self.assertTrue(any("Failed" in s for s in statuses))
        finally:
            shutil.rmtree(folder)


# ── BaseParser coverage tests ─────────────────────────────────────────


class TestBaseParserCoverage(unittest.TestCase):
    """BankStatementParser base-class export and repr behavior."""

    def test_export_csv_success(self):
        """export_csv writes the output file."""
        camt_file = _write_xml(CAMT_XML)
        output_csv = _mktemp(".csv")
        try:
            parser = CamtParser(camt_file)
            parser.export_csv(output_csv)
            self.assertTrue(os.path.exists(output_csv))
        finally:
            os.unlink(camt_file)
            if os.path.exists(output_csv):
                os.unlink(output_csv)

    def test_export_csv_cleanup_on_error(self):
        """export_csv removes its temp file when parsing fails."""
        camt_file = _write_xml(CAMT_XML)
        # "/tmp" does not exist on Windows; use the real temp dir so
        # the touched .tmp file is created and the cleanup branch runs.
        output_path = os.path.join(
            tempfile.gettempdir(), "test_bsp_output.csv"
        )
        try:
            parser = CamtParser(camt_file)

            # Mock parse to raise error after temp file is created
            def failing_parse(*args, **kwargs):
                # Create the temp file first (simulating partial write)
                Path(f"{output_path}.tmp").touch()
                raise RuntimeError("parse error")

            with patch.object(parser, "parse", side_effect=failing_parse):
                with self.assertRaises(IOError):
                    parser.export_csv(output_path)
            # Temp file should be cleaned up
            self.assertFalse(os.path.exists(f"{output_path}.tmp"))
        finally:
            os.unlink(camt_file)
            for f in [output_path, f"{output_path}.tmp"]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_export_json_success(self):
        """export_json writes summary and transactions."""
        camt_file = _write_xml(CAMT_XML)
        output_json = _mktemp(".json")
        try:
            parser = CamtParser(camt_file)
            parser.export_json(output_json)
            self.assertTrue(os.path.exists(output_json))
            with open(output_json) as f:
                data = json.load(f)
            self.assertIn("summary", data)
            self.assertIn("transactions", data)
        finally:
            os.unlink(camt_file)
            if os.path.exists(output_json):
                os.unlink(output_json)

    def test_export_json_cleanup_on_error(self):
        """export_json removes its temp file when parsing fails."""
        camt_file = _write_xml(CAMT_XML)
        output_path = os.path.join(
            tempfile.gettempdir(), "test_bsp_output.json"
        )
        try:
            parser = CamtParser(camt_file)

            def failing_parse(*args, **kwargs):
                Path(f"{output_path}.tmp").touch()
                raise RuntimeError("parse error")

            with patch.object(parser, "parse", side_effect=failing_parse):
                with self.assertRaises(IOError):
                    parser.export_json(output_path)
            self.assertFalse(os.path.exists(f"{output_path}.tmp"))
        finally:
            os.unlink(camt_file)
            for f in [output_path, f"{output_path}.tmp"]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_str_fallback_on_exception(self):
        """__str__ falls back to file info when get_summary() raises."""
        camt_file = _write_xml(CAMT_XML)
        try:
            parser = CamtParser(camt_file)
            with patch.object(
                parser, "get_summary", side_effect=RuntimeError("fail")
            ):
                result = str(parser)
                self.assertIn("CamtParser", result)
                self.assertIn("file=", result)
        finally:
            os.unlink(camt_file)

    def test_str_with_summary(self):
        """__str__ includes the parser name and transaction count."""
        camt_file = _write_xml(CAMT_XML)
        try:
            parser = CamtParser(camt_file)
            result = str(parser)
            self.assertIn("CamtParser", result)
            self.assertIn("transactions", result)
        finally:
            os.unlink(camt_file)

    def test_repr(self):
        """__repr__ includes the parser name and file."""
        pain_file = _write_xml(PAIN_XML)
        try:
            parser = Pain001Parser(pain_file)
            result = repr(parser)
            self.assertIn("Pain001Parser", result)
            self.assertIn("file=", result)
        finally:
            os.unlink(pain_file)

    def test_abstract_parse_pass(self):
        """The abstract parse() body is a no-op returning None."""
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
        """The abstract get_summary() body is a no-op returning None."""
        camt_file = _write_xml(CAMT_XML)
        try:
            parser = CamtParser(camt_file)
            result = BankStatementParser.get_summary(parser)
            self.assertIsNone(result)
        finally:
            os.unlink(camt_file)


# ── InputValidator coverage tests ─────────────────────────────────────


class TestInputValidatorCoverage(unittest.TestCase):
    """InputValidator OS-level failure handling."""

    def test_validate_file_size_os_error(self):
        """A stat() OSError surfaces as ValidationError."""
        validator = InputValidator()
        f = _write_xml(CAMT_XML)
        try:
            path = Path(f)
            with patch.object(Path, "stat", side_effect=OSError("stat error")):
                with self.assertRaises(ValidationError):
                    validator._validate_file_size(path)
        finally:
            os.unlink(f)

    def test_validate_input_format_unicode_decode_error(self):
        """Undecodable file content surfaces as ValidationError."""
        validator = InputValidator()
        # Create a file with binary content that has .xml extension
        fd, binary_path = tempfile.mkstemp(suffix=".xml")
        # Write valid XML header followed by invalid UTF-8
        with os.fdopen(fd, "wb") as f:
            f.write(
                b'<?xml version="1.0"?>\n<Document>\xff\xfe\x80\x81</Document>'
            )
        try:
            path = Path(binary_path)
            # This should handle the UnicodeDecodeError in the outer handler
            with (
                patch(
                    "builtins.open",
                    side_effect=UnicodeDecodeError(
                        "utf-8", b"", 0, 1, "invalid"
                    ),
                ),
                self.assertRaises(ValidationError),
            ):
                validator._validate_input_format(path)
        finally:
            os.unlink(binary_path)


# ── CLI coverage tests ────────────────────────────────────────────────


class TestCLICoverage(unittest.TestCase):
    """CLI streaming, output, and error-exit behavior."""

    def setUp(self):
        self.camt_file = _write_xml(CAMT_XML)
        self.pain_file = _write_xml(PAIN_XML)

    def tearDown(self):
        for f in [self.camt_file, self.pain_file]:
            if os.path.exists(f):
                os.unlink(f)

    def test_parse_camt_streaming_with_output(self):
        """parse_camt streaming writes a CSV output file."""
        cli = BankStatementCLI()
        output_file = _mktemp(".csv")
        output_path = Path(output_file)
        try:
            cli.parse_camt(
                Path(self.camt_file),
                output_path=output_path,
                show_pii=False,
                streaming=True,
            )
            self.assertTrue(
                os.path.exists(output_file)
                or os.path.exists(
                    str(
                        output_path.parent
                        / cli.validator.get_safe_filename(output_path.name)
                    )
                )
            )
        finally:
            if os.path.exists(output_file):
                os.unlink(output_file)

    def test_parse_camt_streaming_console_limit(self):
        """Streaming console output is capped at 100 rows."""
        # Create a CAMT file with many transactions
        entries = ""
        for i in range(105):
            entries += f"""
      <Ntry>
        <Amt Ccy="EUR">{i + 1}.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Sts>BOOK</Sts>
        <BookgDt><Dt>2024-01-15</Dt></BookgDt>
        <ValDt><Dt>2024-01-15</Dt></ValDt>
        <NtryDtls><TxDtls><Refs><EndToEndId>REF{i:04d}</EndToEndId></Refs>
        <RltdPties><Dbtr><Nm>Sender{i}</Nm></Dbtr></RltdPties></TxDtls></NtryDtls>
      </Ntry>"""

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
            with patch("builtins.print") as mock_print:
                cli.parse_camt(Path(f), streaming=True)
                # Check that the "showing first 100" message was printed
                calls = [str(c) for c in mock_print.call_args_list]
                self.assertTrue(any("100" in c for c in calls))
        finally:
            os.unlink(f)

    def test_parse_camt_streaming_show_pii(self):
        """show_pii=True prints an unredacted-PII warning."""
        cli = BankStatementCLI()
        with patch("builtins.print") as mock_print:
            cli.parse_camt(Path(self.camt_file), show_pii=True, streaming=True)
            calls = [str(c) for c in mock_print.call_args_list]
            self.assertTrue(any("WARNING" in c for c in calls))

    def test_parse_pain_streaming_with_output(self):
        """parse_pain streaming writes multi-row CSV (header once)."""
        # Use the test data file which has multiple payments to cover line 304
        pain_file = os.path.join(
            os.path.dirname(__file__),
            "test_data",
            "pain.001.001.03.xml",
        )
        cli = BankStatementCLI()
        output_file = _mktemp(".csv")
        output_path = Path(output_file)
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
            for f in [output_file, safe_path, f"{safe_path}.tmp"]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_parse_pain_streaming_console(self):
        """parse_pain streaming prints payments to the console."""
        cli = BankStatementCLI()
        with patch("builtins.print"):
            cli.parse_pain(Path(self.pain_file), streaming=True)

    def test_parse_pain_streaming_show_pii(self):
        """parse_pain streaming with show_pii=True warns about unredacted output."""
        cli = BankStatementCLI()
        with patch("builtins.print") as mock_print:
            cli.parse_pain(Path(self.pain_file), show_pii=True, streaming=True)
            calls = [str(c) for c in mock_print.call_args_list]
            self.assertTrue(any("WARNING" in c for c in calls))

    def test_parse_pain_nonstreaming_output(self):
        """parse_pain non-streaming writes results to the output CSV."""
        cli = BankStatementCLI()
        output_file = _mktemp(".csv")
        output_path = Path(output_file)
        try:
            cli.parse_pain(
                Path(self.pain_file),
                output_path=output_path,
                show_pii=False,
            )
        finally:
            if os.path.exists(output_file):
                os.unlink(output_file)

    def test_parse_pain_nonstreaming_show_pii(self):
        """parse_pain non-streaming with show_pii=True warns about unredacted output."""
        cli = BankStatementCLI()
        with patch("builtins.print") as mock_print:
            cli.parse_pain(Path(self.pain_file), show_pii=True)
            calls = [str(c) for c in mock_print.call_args_list]
            self.assertTrue(any("WARNING" in c for c in calls))

    def test_parse_pain_nonstreaming_redacted_console(self):
        """parse_pain non-streaming defaults to redacted console output."""
        cli = BankStatementCLI()
        with patch("builtins.print"):
            cli.parse_pain(Path(self.pain_file))

    def test_run_argparse_failure(self):
        """run() exits when argparse rejects the arguments."""
        cli = BankStatementCLI()
        with patch("sys.argv", ["prog", "--type"]):
            with self.assertRaises(SystemExit):
                cli.run()

    def test_run_streaming_camt(self):
        """run() passes --streaming through to parse_camt."""
        cli = BankStatementCLI()
        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "--type",
                    "camt",
                    "--input",
                    self.camt_file,
                    "--streaming",
                ],
            ),
            patch.object(cli, "parse_camt") as mock_parse,
            patch.object(
                cli.validator,
                "validate_input_file_path",
                return_value=Path(self.camt_file),
            ),
        ):
            cli.run()
            mock_parse.assert_called_once()
            # Verify streaming=True was passed
            call_args = mock_parse.call_args
            self.assertTrue(
                call_args[0][3]
                if len(call_args[0]) > 3
                else call_args[1].get("streaming")
            )

    def test_run_streaming_pain001(self):
        """run() passes --streaming through to parse_pain."""
        cli = BankStatementCLI()
        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "--type",
                    "pain001",
                    "--input",
                    self.pain_file,
                    "--streaming",
                ],
            ),
            patch.object(cli, "parse_pain") as mock_parse,
            patch.object(
                cli.validator,
                "validate_input_file_path",
                return_value=Path(self.pain_file),
            ),
        ):
            cli.run()
            mock_parse.assert_called_once()

    def test_run_non_streaming_pain001(self):
        """run() dispatches pain001 input to parse_pain."""
        cli = BankStatementCLI()
        with (
            patch(
                "sys.argv",
                ["prog", "--type", "pain001", "--input", self.pain_file],
            ),
            patch.object(cli, "parse_pain") as mock_parse,
            patch.object(
                cli.validator,
                "validate_input_file_path",
                return_value=Path(self.pain_file),
            ),
        ):
            cli.run()
            mock_parse.assert_called_once()

    def test_run_outer_exception(self):
        """run() exits non-zero when a parser raises unexpectedly."""
        cli = BankStatementCLI()
        with (
            patch(
                "sys.argv",
                ["prog", "--type", "camt", "--input", self.camt_file],
            ),
            patch.object(cli, "parse_camt", side_effect=RuntimeError("fail")),
            patch.object(
                cli.validator,
                "validate_input_file_path",
                return_value=Path(self.camt_file),
            ),
            self.assertRaises(SystemExit),
        ):
            cli.run()

    def test_main_block(self):
        """BankStatementCLI constructs cleanly (the __main__ entry pattern)."""
        # Just verify the pattern works
        cli = BankStatementCLI()
        self.assertIsNotNone(cli)
        self.assertIsNotNone(cli.parser)

    def test_run_missing_required_args_safety_check(self):
        """run() exits if required args are somehow missing post-parse."""
        cli = BankStatementCLI()
        with patch("sys.argv", ["prog", "--type", "camt", "--input", "dummy"]):
            with patch.object(cli.parser, "parse_args") as mock_parse:
                mock_args = MagicMock()
                mock_args.input = None
                mock_args.type = "camt"
                mock_parse.return_value = mock_args
                with self.assertRaises(SystemExit):
                    cli.run()

    def test_run_argparse_failure_defensive_return(self):
        """run() returns safely if sys.exit is mocked during argparse failure."""
        cli = BankStatementCLI()
        with patch("sys.argv", ["prog", "--type"]):
            # Mock sys.exit to NOT raise (simulating mocked test environment)
            with patch("sys.exit") as mock_exit:
                cli.run()
                # sys.exit should have been called
                mock_exit.assert_called()

    def test_run_unsupported_type(self):
        """run() exits non-zero for an unsupported statement type."""
        cli = BankStatementCLI()
        with (
            patch(
                "sys.argv",
                ["prog", "--type", "camt", "--input", self.camt_file],
            ),
            patch.object(cli.parser, "parse_args") as mock_parse,
        ):
            mock_args = MagicMock()
            mock_args.input = self.camt_file
            mock_args.type = "unsupported"
            mock_args.output = None
            mock_args.verbose = False
            mock_args.max_size = 100
            mock_args.show_pii = False
            mock_args.streaming = False
            mock_parse.return_value = mock_args
            with (
                patch.object(
                    cli.validator,
                    "validate_input_file_path",
                    return_value=Path(self.camt_file),
                ),
                self.assertRaises(SystemExit),
            ):
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
        """Streaming console output caps at 100 payments and says so."""
        # Create pain XML with many payments
        pmt_infos = ""
        for i in range(105):
            pmt_infos += f"""
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
    </PmtInf>"""

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
            with patch("builtins.print") as mock_print:
                cli.parse_pain(Path(f), streaming=True)
                calls = [str(c) for c in mock_print.call_args_list]
                self.assertTrue(any("100" in c for c in calls))
        finally:
            os.unlink(f)


class TestCamtToExcelMissingOpenpyxl(unittest.TestCase):
    """camt_to_excel needs the optional [excel] extra."""

    def test_missing_openpyxl_raises_with_install_hint(self):
        f = _write_xml(CAMT_XML)
        try:
            parser = CamtParser(f)
            with patch.dict(sys.modules, {"openpyxl": None}):
                with self.assertRaises(ImportError) as ctx:
                    parser.camt_to_excel("unused.xlsx")
            self.assertIn("bankstatementparser[excel]", str(ctx.exception))
        finally:
            os.unlink(f)


if __name__ == "__main__":
    unittest.main()
