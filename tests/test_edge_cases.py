"""
Edge case tests for bank statement parsers.

Tests for boundary conditions, error handling, and edge scenarios.
"""

import os
import tempfile
import unittest
from decimal import Decimal

import pandas as pd

from bankstatementparser.bank_statement_parsers import (
    Camt053Parser,
    FileParserError,
)
from bankstatementparser.bank_statement_parsers import (
    Pain001Parser as BankPain001Parser,
)
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.input_validator import ValidationError
from bankstatementparser.pain001_parser import Pain001Parser


class TestCamtParserEdgeCases(unittest.TestCase):
    """Test edge cases for CAMT parser."""

    def test_empty_statements(self):
        """Test handling of XML with no statements."""
        empty_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <!-- No statements -->
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(empty_xml)
            empty_file = f.name

        try:
            parser = CamtParser(empty_file)
            stats = parser.get_statement_stats()
            balances = parser.get_account_balances()
            transactions = parser.get_transactions()

            # Should return empty DataFrames
            self.assertEqual(len(stats), 0)
            self.assertEqual(len(balances), 0)
            self.assertEqual(len(transactions), 0)
        finally:
            os.unlink(empty_file)

    def test_statements_without_transactions(self):
        """Test statements with no transaction entries."""
        no_tx_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <CreDtTm>2023-01-01T10:00:00</CreDtTm>
            <Acct>
                <Id><IBAN>GB29NWBK60161331926819</IBAN></Id>
                <Nm>Test Account</Nm>
            </Acct>
            <Bal>
                <Amt Ccy="EUR">1000.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <Tp><Cd>CLBD</Cd></Tp>
                <Dt><Dt>2023-01-01</Dt></Dt>
            </Bal>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(no_tx_xml)
            test_file = f.name

        try:
            parser = CamtParser(test_file)
            stats = parser.get_statement_stats()
            transactions = parser.get_transactions()

            self.assertEqual(len(stats), 1)
            self.assertEqual(stats.iloc[0]["NumTransactions"], 0)
            self.assertEqual(stats.iloc[0]["NetAmount"], 0)
            self.assertEqual(len(transactions), 0)
        finally:
            os.unlink(test_file)

    def test_missing_required_fields(self):
        """Test handling of missing required fields."""
        missing_fields_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct>
                <!-- Missing IBAN -->
                <Nm>Test Account</Nm>
            </Acct>
            <Ntry>
                <!-- Missing amount -->
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-01</Dt></ValDt>
            </Ntry>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(missing_fields_xml)
            test_file = f.name

        try:
            # Parser should handle missing fields gracefully by skipping malformed entries
            parser = CamtParser(test_file)
            result = parser.get_transactions()
            # Malformed entry is skipped, so result should be empty
            self.assertEqual(len(result), 0)
        finally:
            os.unlink(test_file)

    def test_zero_and_negative_amounts(self):
        """Test handling of zero and negative amounts."""
        amounts_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
            <Ntry>
                <Amt Ccy="EUR">0.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-01</Dt></ValDt>
            </Ntry>
            <Ntry>
                <Amt Ccy="EUR">100.00</Amt>
                <CdtDbtInd>DBIT</CdtDbtInd>
                <ValDt><Dt>2023-01-02</Dt></ValDt>
            </Ntry>
            <Ntry>
                <Amt Ccy="EUR">0.01</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-03</Dt></ValDt>
            </Ntry>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(amounts_xml)
            test_file = f.name

        try:
            parser = CamtParser(test_file)
            transactions = parser.get_transactions()

            self.assertEqual(len(transactions), 3)
            self.assertEqual(transactions.iloc[0]["Amount"], 0.00)
            self.assertEqual(
                transactions.iloc[1]["Amount"], -100.00
            )  # DBIT is negative
            self.assertEqual(
                transactions.iloc[2]["Amount"], Decimal("0.01")
            )
        finally:
            os.unlink(test_file)

    def test_very_large_amounts(self):
        """Test handling of very large monetary amounts."""
        large_amounts_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
            <Ntry>
                <Amt Ccy="EUR">999999999999.99</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-01</Dt></ValDt>
            </Ntry>
            <Ntry>
                <Amt Ccy="EUR">0.000001</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-02</Dt></ValDt>
            </Ntry>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(large_amounts_xml)
            test_file = f.name

        try:
            parser = CamtParser(test_file)
            transactions = parser.get_transactions()

            self.assertEqual(len(transactions), 2)
            self.assertEqual(
                transactions.iloc[0]["Amount"],
                Decimal("999999999999.99"),
            )
            self.assertEqual(
                transactions.iloc[1]["Amount"], Decimal("0.000001")
            )
        finally:
            os.unlink(test_file)

    def test_special_characters_in_text_fields(self):
        """Test handling of special characters in text fields."""
        special_chars_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT&amp;001</Id>
            <Acct>
                <Id><IBAN>GB29NWBK60161331926819</IBAN></Id>
                <Nm>Test &lt;Account&gt; "Name" &amp; More</Nm>
            </Acct>
            <Ntry>
                <Amt Ccy="EUR">100.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-01</Dt></ValDt>
                <NtryDtls>
                    <TxDtls>
                        <RmtInf>
                            <Ustrd>Payment for "goods &amp; services" &lt;order #123&gt;</Ustrd>
                        </RmtInf>
                        <RltdPties>
                            <Dbtr><Nm>John "Doe" &amp; Co.</Nm></Dbtr>
                            <Cdtr><Nm>Jane &lt;Smith&gt;</Nm></Cdtr>
                        </RltdPties>
                    </TxDtls>
                </NtryDtls>
            </Ntry>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(special_chars_xml)
            test_file = f.name

        try:
            parser = CamtParser(test_file)
            transactions = parser.get_transactions()

            self.assertEqual(len(transactions), 1)
            # Verify special characters are properly decoded
            self.assertIn(
                "goods & services", transactions.iloc[0]["Reference"]
            )
            self.assertIn(
                "<order #123>", transactions.iloc[0]["Reference"]
            )
            self.assertEqual(
                transactions.iloc[0]["Debtor"], 'John "Doe" & Co.'
            )
            self.assertEqual(
                transactions.iloc[0]["Creditor"], "Jane <Smith>"
            )
        finally:
            os.unlink(test_file)

    def test_multiple_currencies(self):
        """Test handling of multiple currencies."""
        multi_currency_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
            <Ntry>
                <Amt Ccy="EUR">100.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-01</Dt></ValDt>
            </Ntry>
            <Ntry>
                <Amt Ccy="USD">200.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-02</Dt></ValDt>
            </Ntry>
            <Ntry>
                <Amt Ccy="GBP">150.00</Amt>
                <CdtDbtInd>DBIT</CdtDbtInd>
                <ValDt><Dt>2023-01-03</Dt></ValDt>
            </Ntry>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(multi_currency_xml)
            test_file = f.name

        try:
            parser = CamtParser(test_file)
            transactions = parser.get_transactions()

            self.assertEqual(len(transactions), 3)
            currencies = set(transactions["Currency"])
            self.assertEqual(currencies, {"EUR", "USD", "GBP"})

            # Verify amounts and signs
            self.assertEqual(transactions.iloc[0]["Amount"], 100.00)
            self.assertEqual(transactions.iloc[1]["Amount"], 200.00)
            self.assertEqual(transactions.iloc[2]["Amount"], -150.00)
        finally:
            os.unlink(test_file)

    def test_date_format_variations(self):
        """Test handling of different date formats."""
        date_formats_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
            <Ntry>
                <Amt Ccy="EUR">100.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-01</Dt></ValDt>
                <BookgDt><Dt>2023-01-01</Dt></BookgDt>
            </Ntry>
            <Ntry>
                <Amt Ccy="EUR">200.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><DtTm>2023-01-02T14:30:00</DtTm></ValDt>
                <BookgDt><DtTm>2023-01-02T14:30:00</DtTm></BookgDt>
            </Ntry>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(date_formats_xml)
            test_file = f.name

        try:
            parser = CamtParser(test_file)
            transactions = parser.get_transactions()

            self.assertEqual(len(transactions), 2)
            self.assertEqual(
                transactions.iloc[0]["ValDt"], "2023-01-01"
            )
            self.assertEqual(
                transactions.iloc[1]["ValDt"], "2023-01-02T14:30:00"
            )
        finally:
            os.unlink(test_file)

    def test_excel_export_edge_cases(self):
        """Test Excel export with edge cases."""
        # Create parser with minimal data
        minimal_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(minimal_xml)
            test_file = f.name

        try:
            parser = CamtParser(test_file)

            # Test export to Excel
            with tempfile.NamedTemporaryFile(
                suffix=".xlsx", delete=False
            ) as excel_f:
                excel_file = excel_f.name

            try:
                parser.camt_to_excel(excel_file)
                self.assertTrue(os.path.exists(excel_file))
                self.assertGreater(os.path.getsize(excel_file), 0)

                # Verify Excel file can be read back
                balances_df = pd.read_excel(
                    excel_file, sheet_name="Balances"
                )
                transactions_df = pd.read_excel(
                    excel_file, sheet_name="Transactions"
                )
                stats_df = pd.read_excel(excel_file, sheet_name="Stats")

                self.assertIsInstance(balances_df, pd.DataFrame)
                self.assertIsInstance(transactions_df, pd.DataFrame)
                self.assertIsInstance(stats_df, pd.DataFrame)

            finally:
                if os.path.exists(excel_file):
                    os.unlink(excel_file)

        finally:
            os.unlink(test_file)


class TestPain001ParserEdgeCases(unittest.TestCase):
    """Test edge cases for Pain001 parser."""

    def test_missing_optional_fields(self):
        """Test handling of missing optional fields."""
        minimal_pain001 = """<?xml version="1.0"?>
<Document>
    <CstmrCdtTrfInitn>
        <GrpHdr>
            <MsgId>MSG001</MsgId>
            <CreDtTm>2023-01-01T10:00:00</CreDtTm>
            <NbOfTxs>1</NbOfTxs>
            <InitgPty><Nm>Initiator</Nm></InitgPty>
        </GrpHdr>
        <PmtInf>
            <PmtInfId>PMT001</PmtInfId>
        </PmtInf>
    </CstmrCdtTrfInitn>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(minimal_pain001)
            test_file = f.name

        try:
            parser = Pain001Parser(test_file)
            result = parser.parse()
            self.assertIsInstance(result, pd.DataFrame)
        finally:
            os.unlink(test_file)

    def test_empty_group_header(self):
        """Test handling of empty group header."""
        empty_header_xml = """<?xml version="1.0"?>
<Document>
    <CstmrCdtTrfInitn>
        <GrpHdr>
        </GrpHdr>
    </CstmrCdtTrfInitn>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(empty_header_xml)
            test_file = f.name

        try:
            parser = Pain001Parser(test_file)
            # Should handle gracefully without crashing
            result = parser.parse()
            self.assertIsInstance(result, pd.DataFrame)
        finally:
            os.unlink(test_file)


class TestBankStatementParsersEdgeCases(unittest.TestCase):
    """Test edge cases for bank statement parsers module."""

    def test_pain001_parser_edge_cases(self):
        """Test Pain001Parser edge cases."""
        # Test with minimal valid structure
        minimal_xml = """<?xml version="1.0"?>
<Document>
    <CstmrCdtTrfInitn>
        <PmtInf>
            <ReqdExctnDt>2023-01-01</ReqdExctnDt>
            <Dbtr><Nm>Debtor</Nm></Dbtr>
            <CdtTrfTxInf>
                <InstdAmt Ccy="EUR">0.01</InstdAmt>
                <Cdtr><Nm>Creditor</Nm></Cdtr>
            </CdtTrfTxInf>
        </PmtInf>
    </CstmrCdtTrfInitn>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(minimal_xml)
            test_file = f.name

        try:
            parser = BankPain001Parser(test_file)
            self.assertEqual(parser.batches_count, 1)
            self.assertEqual(parser.total_payments_count, 1)
            self.assertEqual(len(parser.payments), 1)

            payment = parser.payments[0]
            self.assertEqual(payment["Amount"], Decimal("0.01"))
            self.assertEqual(payment["Currency"], "EUR")
            self.assertEqual(payment["Name"], "Creditor")

        finally:
            os.unlink(test_file)

    def test_camt053_parser_edge_cases(self):
        """Test Camt053Parser edge cases."""
        # Test with minimal valid structure
        minimal_camt = """<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(minimal_camt)
            test_file = f.name

        try:
            parser = Camt053Parser(test_file)
            self.assertEqual(len(parser.statements), 1)
            self.assertEqual(len(parser.transactions), 0)

            statement = parser.statements[0]
            self.assertEqual(statement["StatementId"], "STMT001")
            self.assertEqual(
                statement["AccountId"], "GB29NWBK60161331926819"
            )

        finally:
            os.unlink(test_file)

    def test_invalid_camt_file_detection(self):
        """Test detection of invalid CAMT files."""
        # Test non-XML file
        non_xml = "This is not XML content"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(non_xml)
            test_file = f.name

        try:
            with self.assertRaises(FileParserError):
                Camt053Parser(test_file)
        finally:
            os.unlink(test_file)

    def test_repr_methods(self):
        """Test string representations of parser objects."""
        # Test CAMT parser representation
        test_camt = """<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
            <Ntry>
                <Amt Ccy="EUR">100.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-01</Dt></ValDt>
            </Ntry>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(test_camt)
            camt_file = f.name

        try:
            parser = Camt053Parser(camt_file)
            repr_str = repr(parser)
            self.assertIn("Camt053Parser", repr_str)
            self.assertIn("statements=1", repr_str)
            self.assertIn("transactions=1", repr_str)
        finally:
            os.unlink(camt_file)

        # Test Pain001 parser representation
        test_pain001 = """<?xml version="1.0"?>
<Document>
    <CstmrCdtTrfInitn>
        <PmtInf>
            <ReqdExctnDt>2023-01-01</ReqdExctnDt>
            <Dbtr><Nm>Debtor</Nm></Dbtr>
            <CdtTrfTxInf>
                <InstdAmt Ccy="EUR">100.00</InstdAmt>
                <Cdtr><Nm>Creditor</Nm></Cdtr>
            </CdtTrfTxInf>
            <CdtTrfTxInf>
                <InstdAmt Ccy="EUR">200.00</InstdAmt>
                <Cdtr><Nm>Creditor2</Nm></Cdtr>
            </CdtTrfTxInf>
        </PmtInf>
    </CstmrCdtTrfInitn>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(test_pain001)
            pain_file = f.name

        try:
            parser = BankPain001Parser(pain_file)
            repr_str = repr(parser)
            self.assertIn("Pain001Parser", repr_str)
            self.assertIn("batches=1", repr_str)
            self.assertIn("payments=2", repr_str)
        finally:
            os.unlink(pain_file)


class TestErrorConditions(unittest.TestCase):
    """Test various error conditions and exception handling."""

    def test_file_permission_errors(self):
        """Test handling of file permission errors."""
        # Create a file and remove read permissions
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write('<?xml version="1.0"?><Document></Document>')
            test_file = f.name

        try:
            # Remove read permissions
            os.chmod(test_file, 0o000)

            with self.assertRaises(
                (PermissionError, OSError, ValidationError)
            ):
                CamtParser(test_file)

        finally:
            # Restore permissions and cleanup
            os.chmod(test_file, 0o644)
            os.unlink(test_file)

    def test_concurrent_access(self):
        """Test handling of concurrent file access."""
        test_xml = """<?xml version="1.0"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(test_xml)
            test_file = f.name

        try:
            # Multiple parsers accessing the same file
            parser1 = CamtParser(test_file)
            parser2 = CamtParser(test_file)

            # Both should work independently
            stats1 = parser1.get_statement_stats()
            stats2 = parser2.get_statement_stats()

            self.assertEqual(len(stats1), 1)
            self.assertEqual(len(stats2), 1)

        finally:
            os.unlink(test_file)

    def test_memory_cleanup(self):
        """Test that parsers properly clean up memory."""
        import gc

        test_xml = """<?xml version="1.0"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(test_xml)
            test_file = f.name

        try:
            # Create parser and let it go out of scope
            def create_parser():
                parser = CamtParser(test_file)
                parser.get_statement_stats()
                return len(parser.get_statement_stats())

            result = create_parser()
            self.assertEqual(result, 1)

            # Force garbage collection
            gc.collect()

            # Memory should be cleaned up
            # This is more of a smoke test as actual memory measurement is complex

        finally:
            os.unlink(test_file)


if __name__ == "__main__":
    unittest.main(verbosity=2)
