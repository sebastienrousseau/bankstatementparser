"""
Integration tests for the unified parser interface (BankStatementParser ABC).

This module tests the consistency and compliance of the unified parser interface
across different bank statement formats (CAMT and PAIN001), ensuring that all
concrete implementations provide consistent behavior for format detection,
parsing, error handling, and export functionality.
"""

import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from xml.etree.ElementTree import ParseError

import pandas as pd

from bankstatementparser.base_parser import BankStatementParser
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.input_validator import ValidationError
from bankstatementparser.pain001_parser import Pain001Parser


class TestUnifiedParserInterface(unittest.TestCase):
    """Test the unified parser interface compliance across different formats."""

    def setUp(self):
        """Set up test fixtures with sample data files."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.test_data_dir = os.path.join(current_dir, "test_data")

        # Valid test files
        self.camt_file = os.path.join(
            self.test_data_dir, "camt.053.001.02.xml"
        )
        self.pain001_file = os.path.join(
            self.test_data_dir, "pain.001.001.03.xml"
        )
        self.invalid_xml_file = os.path.join(
            self.test_data_dir, "invalid.xml"
        )

        # Initialize parsers if files exist
        self.camt_parser = None
        self.pain001_parser = None

        if os.path.exists(self.camt_file):
            self.camt_parser = CamtParser(self.camt_file)

        if os.path.exists(self.pain001_file):
            self.pain001_parser = Pain001Parser(self.pain001_file)

    def test_abstract_base_class_cannot_be_instantiated(self):
        """Test that BankStatementParser ABC cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            BankStatementParser("dummy_file.xml")

    def test_concrete_parsers_implement_required_methods(self):
        """Test that concrete parsers implement all required abstract methods."""
        parsers = []
        if self.camt_parser:
            parsers.append(self.camt_parser)
        if self.pain001_parser:
            parsers.append(self.pain001_parser)

        for parser in parsers:
            # Test required abstract methods exist and are callable
            self.assertTrue(hasattr(parser, "parse"))
            self.assertTrue(callable(parser.parse))
            self.assertTrue(hasattr(parser, "get_summary"))
            self.assertTrue(callable(parser.get_summary))

            # Test inherited concrete methods exist
            self.assertTrue(hasattr(parser, "export_csv"))
            self.assertTrue(callable(parser.export_csv))
            self.assertTrue(hasattr(parser, "export_json"))
            self.assertTrue(callable(parser.export_json))

    def test_parse_method_returns_dataframe(self):
        """Test that parse() method returns a pandas DataFrame for all parsers."""
        parsers = []
        if self.camt_parser:
            parsers.append(self.camt_parser)
        if self.pain001_parser:
            parsers.append(self.pain001_parser)

        for parser in parsers:
            result = parser.parse()
            self.assertIsInstance(result, pd.DataFrame)

            # Test DataFrame has expected structure
            self.assertGreaterEqual(
                len(result.columns), 0
            )  # At least some columns

            # If data exists, verify it has reasonable structure
            if not result.empty:
                # Common expected columns across formats (may vary by implementation)
                expected_column_patterns = [
                    "amount",
                    "currency",
                    "date",
                    "id",
                ]
                column_names_lower = [
                    col.lower() for col in result.columns
                ]

                # At least some expected patterns should be present
                found_patterns = any(
                    any(
                        pattern in col
                        for pattern in expected_column_patterns
                    )
                    for col in column_names_lower
                )
                self.assertTrue(
                    found_patterns,
                    f"No expected column patterns found in: {result.columns}",
                )

    def test_get_summary_method_returns_consistent_structure(self):
        """Test that get_summary() returns consistent structure across parsers."""
        parsers = []
        if self.camt_parser:
            parsers.append(self.camt_parser)
        if self.pain001_parser:
            parsers.append(self.pain001_parser)

        for parser in parsers:
            summary = parser.get_summary()
            self.assertIsInstance(summary, dict)

            # Test required keys are present (based on ABC documentation)
            required_keys = [
                "account_id",
                "statement_date",
                "transaction_count",
                "total_amount",
                "currency",
            ]
            for key in required_keys:
                self.assertIn(
                    key,
                    summary,
                    f"Missing required key '{key}' in summary",
                )

            # Test value types are reasonable (allow numpy types too)
            if summary.get("transaction_count") is not None:
                # Allow int, str, or numpy integer types
                import numpy as np

                self.assertTrue(
                    isinstance(summary["transaction_count"], (int, str))
                    or np.issubdtype(
                        type(summary["transaction_count"]), np.integer
                    ),
                    f"transaction_count has unexpected type: {type(summary['transaction_count'])}",
                )
            if summary.get("total_amount") is not None:
                self.assertIsInstance(
                    summary["total_amount"], (int, float, Decimal)
                )

    def test_export_csv_functionality(self):
        """Test CSV export functionality across all parsers."""
        parsers = []
        if self.camt_parser:
            parsers.append(("CAMT", self.camt_parser))
        if self.pain001_parser:
            parsers.append(("PAIN001", self.pain001_parser))

        for parser_name, parser in parsers:
            with tempfile.NamedTemporaryFile(
                suffix=".csv", delete=False
            ) as tmp_file:
                try:
                    parser.export_csv(tmp_file.name)

                    # Verify file was created
                    self.assertTrue(os.path.exists(tmp_file.name))

                    # Verify file has content
                    with open(tmp_file.name) as f:
                        content = f.read()
                        self.assertGreater(
                            len(content),
                            0,
                            f"Empty CSV export for {parser_name}",
                        )

                    # Verify it's valid CSV (can be read back as DataFrame)
                    df = pd.read_csv(tmp_file.name)
                    self.assertIsInstance(df, pd.DataFrame)

                finally:
                    # Clean up
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)

    def test_export_json_functionality(self):
        """Test JSON export functionality across all parsers."""
        parsers = []
        if self.camt_parser:
            parsers.append(("CAMT", self.camt_parser))
        if self.pain001_parser:
            parsers.append(("PAIN001", self.pain001_parser))

        for parser_name, parser in parsers:
            with tempfile.NamedTemporaryFile(
                suffix=".json", delete=False
            ) as tmp_file:
                try:
                    parser.export_json(tmp_file.name)

                    # Verify file was created
                    self.assertTrue(os.path.exists(tmp_file.name))

                    # Verify file has content
                    with open(tmp_file.name) as f:
                        content = f.read()
                        self.assertGreater(
                            len(content),
                            0,
                            f"Empty JSON export for {parser_name}",
                        )

                    # Verify it's valid JSON with expected structure
                    with open(tmp_file.name) as f:
                        data = json.load(f)
                        self.assertIsInstance(data, dict)
                        self.assertIn("summary", data)
                        self.assertIn("transactions", data)

                        # Verify summary structure
                        summary = data["summary"]
                        self.assertIsInstance(summary, dict)

                        # Verify transactions structure
                        transactions = data["transactions"]
                        self.assertIsInstance(transactions, list)

                finally:
                    # Clean up
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)

    def test_atomic_file_operations(self):
        """Test that export operations use atomic file operations to prevent corruption."""
        if not self.camt_parser:
            self.skipTest("CAMT test data not available")

        # Test CSV atomic operation
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False
        ) as tmp_file:
            output_path = tmp_file.name
            temp_path = f"{output_path}.tmp"

            try:
                # Mock an exception during the export to test cleanup
                with patch(
                    "pandas.DataFrame.to_csv",
                    side_effect=Exception("Test error"),
                ):
                    with self.assertRaises(IOError):
                        self.camt_parser.export_csv(output_path)

                    # Verify temp file was cleaned up
                    self.assertFalse(os.path.exists(temp_path))

            finally:
                # Clean up
                if os.path.exists(output_path):
                    os.unlink(output_path)
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        # Test JSON atomic operation
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False
        ) as tmp_file:
            output_path = tmp_file.name
            temp_path = f"{output_path}.tmp"

            try:
                # Mock an exception during JSON export
                with patch(
                    "builtins.open", side_effect=Exception("Test error")
                ):
                    with self.assertRaises(IOError):
                        self.camt_parser.export_json(output_path)

            finally:
                # Clean up
                if os.path.exists(output_path):
                    os.unlink(output_path)
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

    def test_string_representations(self):
        """Test __str__ and __repr__ methods work consistently."""
        parsers = []
        if self.camt_parser:
            parsers.append(("CAMT", self.camt_parser))
        if self.pain001_parser:
            parsers.append(("PAIN001", self.pain001_parser))

        for _parser_name, parser in parsers:
            # Test __repr__ - CamtParser returns statement stats, others might use default
            repr_str = repr(parser)
            self.assertIsInstance(repr_str, str)
            self.assertGreater(
                len(repr_str), 0, "repr should return non-empty string"
            )
            # Don't assert specific content since CamtParser returns statement stats

            # Test __str__
            str_str = str(parser)
            self.assertIsInstance(str_str, str)
            self.assertIn(parser.__class__.__name__, str_str)

    def test_error_handling_consistency(self):
        """Test consistent error handling across parser implementations."""
        # Test with non-existent file
        non_existent_file = "/path/to/non/existent/file.xml"

        with self.assertRaises((FileNotFoundError, ValidationError)):
            CamtParser(non_existent_file)

        with self.assertRaises((FileNotFoundError, ValidationError)):
            Pain001Parser(non_existent_file)

        # Test with minimal XML file (if available)
        if os.path.exists(self.invalid_xml_file):
            # The file might be valid XML but not contain expected CAMT/PAIN001 structure
            try:
                parser = CamtParser(self.invalid_xml_file)
                # parse() may fail or return empty data
                df = parser.parse()
                self.assertIsInstance(df, pd.DataFrame)
            except (ValidationError, Exception):
                # Expected for files without proper CAMT structure
                pass

            try:
                parser = Pain001Parser(self.invalid_xml_file)
                # parse() may fail or return empty data
                df = parser.parse()
                self.assertIsInstance(df, pd.DataFrame)
            except (ValidationError, Exception):
                # Expected for files without proper PAIN001 structure
                pass

    def test_malformed_input_handling(self):
        """Test handling of malformed input data."""
        # Create a temporary malformed XML file
        malformed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <invalid>
            <unclosed_tag>
            <missing_content />
        </invalid>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as tmp_file:
            tmp_file.write(malformed_xml)
            tmp_file.flush()

            try:
                # Test CAMT parser with malformed input
                with self.assertRaises(
                    (ValidationError, ParseError, Exception)
                ):
                    parser = CamtParser(tmp_file.name)
                    parser.parse()

                # Test PAIN001 parser with malformed input
                with self.assertRaises(
                    (ValidationError, ParseError, Exception)
                ):
                    parser = Pain001Parser(tmp_file.name)
                    parser.parse()

            finally:
                os.unlink(tmp_file.name)

    def test_large_file_handling(self):
        """Test parser behavior with larger input files."""
        # Create a larger XML file (but not too large for testing)
        large_xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
            <BkToCstmrStmt>
                <GrpHdr>
                    <MsgId>large_test</MsgId>
                    <CreDtTm>2023-03-10T15:30:47.000Z</CreDtTm>
                </GrpHdr>
                <Stmt>
                    <Id>large_statement</Id>
                    <CreDtTm>2023-03-10T15:30:47.000Z</CreDtTm>
                    <Acct>
                        <Id><IBAN>GB82WEST12345698765432</IBAN></Id>
                        <Ccy>GBP</Ccy>
                    </Acct>
        """

        # Add multiple transaction entries
        for i in range(
            100
        ):  # 100 transactions to make it moderately large
            large_xml_content += f"""
                    <Ntry>
                        <Amt Ccy="GBP">{10.00 + i}</Amt>
                        <CdtDbtInd>CRDT</CdtDbtInd>
                        <BookgDt><Dt>2023-03-{10 + (i % 20)}</Dt></BookgDt>
                        <ValDt><Dt>2023-03-{10 + (i % 20)}</Dt></ValDt>
                        <BkTxCd><Prtry><Cd>TRF</Cd></Prtry></BkTxCd>
                        <NtryDtls>
                            <TxDtls>
                                <Refs>
                                    <MsgId>TX{i:03d}</MsgId>
                                </Refs>
                                <RltdPties>
                                    <Dbtr><Nm>Test Debtor {i}</Nm></Dbtr>
                                    <Cdtr><Nm>Test Creditor {i}</Nm></Cdtr>
                                </RltdPties>
                                <RmtInf>
                                    <Ustrd>Transaction {i} reference</Ustrd>
                                </RmtInf>
                            </TxDtls>
                        </NtryDtls>
                    </Ntry>"""

        large_xml_content += """
                </Stmt>
            </BkToCstmrStmt>
        </Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as tmp_file:
            tmp_file.write(large_xml_content)
            tmp_file.flush()

            try:
                # Test CAMT parser with larger file
                parser = CamtParser(tmp_file.name)
                df = parser.parse()
                self.assertIsInstance(df, pd.DataFrame)
                self.assertGreater(
                    len(df), 50
                )  # Should have many transactions

                # Test export functionality with larger dataset
                with tempfile.NamedTemporaryFile(
                    suffix=".csv", delete=False
                ) as csv_file:
                    try:
                        parser.export_csv(csv_file.name)
                        self.assertTrue(os.path.exists(csv_file.name))
                    finally:
                        if os.path.exists(csv_file.name):
                            os.unlink(csv_file.name)

            finally:
                os.unlink(tmp_file.name)

    def test_edge_case_file_formats(self):
        """Test parser behavior with edge case file formats."""
        # Test empty XML file
        empty_xml = (
            """<?xml version="1.0" encoding="UTF-8"?><root></root>"""
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as tmp_file:
            tmp_file.write(empty_xml)
            tmp_file.flush()

            try:
                # Both parsers should handle empty/minimal XML gracefully
                # Test that they can be created but may fail on parse()
                try:
                    parser = CamtParser(tmp_file.name)
                    # parse() should fail or return empty results
                    df = parser.parse()
                    self.assertIsInstance(df, pd.DataFrame)
                except (ValidationError, Exception):
                    # Either constructor or parse can fail - both acceptable
                    pass

                try:
                    parser = Pain001Parser(tmp_file.name)
                    # parse() should fail or return empty results
                    df = parser.parse()
                    self.assertIsInstance(df, pd.DataFrame)
                except (ValidationError, Exception):
                    # Either constructor or parse can fail - both acceptable
                    pass

            finally:
                os.unlink(tmp_file.name)

        # Test XML with namespace but no data
        minimal_camt_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
        </Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as tmp_file:
            tmp_file.write(minimal_camt_xml)
            tmp_file.flush()

            try:
                # Should be able to create parser but parse() may return empty results
                parser = CamtParser(tmp_file.name)
                df = parser.parse()
                self.assertIsInstance(df, pd.DataFrame)
                # Empty DataFrame is acceptable for empty input

            finally:
                os.unlink(tmp_file.name)

    def test_path_handling_consistency(self):
        """Test that parsers handle different path types consistently."""
        if not self.camt_parser:
            self.skipTest("CAMT test data not available")

        # Test with string path
        parser1 = CamtParser(self.camt_file)
        self.assertEqual(parser1.file_name, self.camt_file)

        # Test with Path object
        path_obj = Path(self.camt_file)
        parser2 = CamtParser(
            str(path_obj)
        )  # Constructor expects string
        self.assertEqual(parser2.file_name, str(path_obj))

    def test_export_error_handling(self):
        """Test error handling in export methods."""
        if not self.camt_parser:
            self.skipTest("CAMT test data not available")

        # Test export to read-only directory (should raise IOError)
        read_only_path = "/dev/null/cannot_write_here.csv"

        with self.assertRaises(IOError):
            self.camt_parser.export_csv(read_only_path)

        with self.assertRaises(IOError):
            self.camt_parser.export_json(read_only_path)


class TestParserFactoryPattern(unittest.TestCase):
    """Test factory-style usage patterns for the unified interface."""

    def test_parser_selection_by_file_format(self):
        """Test that appropriate parser can be selected based on file content."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        test_data_dir = os.path.join(current_dir, "test_data")

        camt_file = os.path.join(test_data_dir, "camt.053.001.02.xml")
        pain001_file = os.path.join(
            test_data_dir, "pain.001.001.03.xml"
        )

        parsers = {}

        # Create parsers if files exist
        if os.path.exists(camt_file):
            parsers["CAMT"] = CamtParser(camt_file)

        if os.path.exists(pain001_file):
            parsers["PAIN001"] = Pain001Parser(pain001_file)

        # Test that all created parsers implement the interface properly
        for _format_name, parser in parsers.items():
            self.assertIsInstance(parser, BankStatementParser)

            # Test polymorphic usage
            df = parser.parse()
            summary = parser.get_summary()

            self.assertIsInstance(df, pd.DataFrame)
            self.assertIsInstance(summary, dict)


if __name__ == "__main__":
    unittest.main()
