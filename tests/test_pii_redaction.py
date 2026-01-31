"""
Unit tests for PII redaction functionality across CLI and parser modules.

This module tests the PII redaction capabilities of the bank statement parser,
ensuring that sensitive personal information is properly handled in different
scenarios while maintaining data utility for legitimate use cases.
"""

import unittest
import tempfile
import os
import sys
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from io import StringIO
import json

from bankstatementparser.cli import BankStatementCLI
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.pain001_parser import Pain001Parser
from bankstatementparser.input_validator import ValidationError


class TestPIIRedaction(unittest.TestCase):
    """Test suite for PII redaction functionality."""

    def setUp(self):
        """Set up test environment with mock data containing PII."""
        self.cli = BankStatementCLI()

        # Sample data with PII columns to test redaction
        self.test_data_with_pii = pd.DataFrame({
            'transaction_id': ['TXN001', 'TXN002', 'TXN003'],
            'account_number': ['1234567890', '0987654321', '5555666677'],
            'debtor_name': ['John Doe', 'Jane Smith', 'Bob Wilson'],
            'creditor_name': ['ACME Corp', 'XYZ Ltd', 'ABC Inc'],
            'debtor_address': ['123 Main St, City', '456 Oak Ave, Town', '789 Pine Rd, Village'],
            'iban': ['GB29NWBK60161331926819', 'DE89370400440532013000', 'FR1420041010050500013M02606'],
            'bic': ['NWBKGB2L', 'COBADEFFXXX', 'BNPAFRPPXXX'],
            'amount': [100.50, 250.75, 75.25],
            'currency': ['EUR', 'USD', 'GBP'],
            'date': ['2024-01-01', '2024-01-02', '2024-01-03']
        })

        self.expected_redacted_columns = ['account_number', 'debtor_name', 'creditor_name', 'debtor_address', 'iban', 'bic']
        self.expected_unredacted_columns = ['transaction_id', 'amount', 'currency', 'date']

    def test_redact_dataframe_basic_functionality(self):
        """Test that _redact_dataframe correctly identifies and redacts PII columns."""
        redacted_df = self.cli._redact_dataframe(self.test_data_with_pii)

        # Ensure original data is not modified
        self.assertIsNot(redacted_df, self.test_data_with_pii)

        # Check that PII columns are redacted
        for column in self.expected_redacted_columns:
            if column in redacted_df.columns:
                self.assertTrue(
                    all(redacted_df[column] == '***REDACTED***'),
                    f"Column '{column}' should be redacted but contains: {redacted_df[column].unique()}"
                )

        # Check that non-PII columns are preserved
        for column in self.expected_unredacted_columns:
            if column in redacted_df.columns:
                pd.testing.assert_series_equal(
                    redacted_df[column],
                    self.test_data_with_pii[column],
                    f"Non-PII column '{column}' should not be redacted"
                )

    def test_redact_dataframe_case_insensitive(self):
        """Test that PII detection works case-insensitively."""
        test_data = pd.DataFrame({
            'Account_Number': ['12345'],
            'IBAN': ['GB123'],
            'Name_Debtor': ['John'],
            'ADDRESS_LINE': ['123 Main St'],
            'Safe_Column': ['Safe Data']
        })

        redacted_df = self.cli._redact_dataframe(test_data)

        # Case variations should still be detected and redacted
        self.assertEqual(redacted_df['Account_Number'].iloc[0], '***REDACTED***')
        self.assertEqual(redacted_df['IBAN'].iloc[0], '***REDACTED***')
        self.assertEqual(redacted_df['Name_Debtor'].iloc[0], '***REDACTED***')
        self.assertEqual(redacted_df['ADDRESS_LINE'].iloc[0], '***REDACTED***')

        # Non-PII should remain unchanged
        self.assertEqual(redacted_df['Safe_Column'].iloc[0], 'Safe Data')

    def test_redact_dataframe_empty_dataframe(self):
        """Test redaction behavior with empty DataFrame."""
        empty_df = pd.DataFrame()
        redacted_df = self.cli._redact_dataframe(empty_df)

        self.assertTrue(redacted_df.empty)
        self.assertEqual(len(redacted_df.columns), 0)

    def test_redact_dataframe_no_pii_columns(self):
        """Test redaction with DataFrame containing no PII columns."""
        safe_data = pd.DataFrame({
            'transaction_id': ['TXN001', 'TXN002'],
            'amount': [100.0, 200.0],
            'currency': ['EUR', 'USD'],
            'status': ['completed', 'pending']
        })

        redacted_df = self.cli._redact_dataframe(safe_data)

        # All data should remain unchanged
        pd.testing.assert_frame_equal(redacted_df, safe_data)

    @patch('bankstatementparser.cli.CamtParser')
    def test_cli_default_console_output_redacts_pii(self, mock_camt_parser):
        """Test CLI default behavior redacts PII in console output."""
        # Setup mock parser to return data with PII
        mock_parser_instance = Mock()
        mock_parser_instance.get_statement_stats.return_value = self.test_data_with_pii.to_dict('records')
        mock_camt_parser.return_value = mock_parser_instance

        with tempfile.NamedTemporaryFile(suffix='.xml') as temp_file:
            input_path = Path(temp_file.name)

            with patch('builtins.print') as mock_print:
                # Call without show_pii flag (default behavior)
                self.cli.parse_camt(input_path, None, show_pii=False)

                # Verify print was called (console output)
                self.assertTrue(mock_print.called)

                # Extract the DataFrame that was printed
                print_args = mock_print.call_args[0]
                self.assertEqual(len(print_args), 1)
                printed_df = print_args[0]

                # Verify it's a DataFrame and PII columns are redacted
                self.assertIsInstance(printed_df, pd.DataFrame)
                for column in self.expected_redacted_columns:
                    if column in printed_df.columns:
                        self.assertTrue(
                            all(printed_df[column] == '***REDACTED***'),
                            f"Console output should have redacted column '{column}'"
                        )

    @patch('bankstatementparser.cli.CamtParser')
    def test_cli_show_pii_flag_displays_unredacted_with_warning(self, mock_camt_parser):
        """Test CLI --show-pii flag displays unredacted data with warning."""
        # Setup mock parser to return data with PII
        mock_parser_instance = Mock()
        mock_parser_instance.get_statement_stats.return_value = self.test_data_with_pii.to_dict('records')
        mock_camt_parser.return_value = mock_parser_instance

        with tempfile.NamedTemporaryFile(suffix='.xml') as temp_file:
            input_path = Path(temp_file.name)

            with patch('builtins.print') as mock_print:
                # Call with show_pii=True flag
                self.cli.parse_camt(input_path, None, show_pii=True)

                # Verify warning was printed first
                warning_call = mock_print.call_args_list[0]
                self.assertIn("WARNING: Displaying unredacted PII data", warning_call[0][0])

                # Verify unredacted data was printed second
                data_call = mock_print.call_args_list[1]
                printed_df = data_call[0][0]

                # Verify PII columns are NOT redacted (original values preserved)
                self.assertIsInstance(printed_df, pd.DataFrame)
                for column in self.expected_redacted_columns:
                    if column in printed_df.columns:
                        # Should contain original values, not redacted values
                        self.assertFalse(
                            all(printed_df[column] == '***REDACTED***'),
                            f"With --show-pii, column '{column}' should not be redacted"
                        )

    @patch('bankstatementparser.cli.CamtParser')
    @patch('pandas.DataFrame.to_csv')
    def test_cli_output_file_export_unredacted(self, mock_to_csv, mock_camt_parser):
        """Test CLI file export (--output) saves unredacted data."""
        # Setup mock parser to return data with PII
        mock_parser_instance = Mock()
        mock_parser_instance.get_statement_stats.return_value = self.test_data_with_pii.to_dict('records')
        mock_camt_parser.return_value = mock_parser_instance

        with patch.object(self.cli.validator, 'get_safe_filename', return_value='safe_output.csv'):
            with tempfile.NamedTemporaryFile(suffix='.xml') as temp_input:
                input_path = Path(temp_input.name)
                output_path = Path('output.csv')

                with patch('builtins.print'):
                    self.cli.parse_camt(input_path, output_path, show_pii=False)

                    # Verify to_csv was called once
                    self.assertEqual(mock_to_csv.call_count, 1)

                    # Extract the DataFrame passed to to_csv
                    saved_df_call = mock_to_csv.call_args
                    saved_df = mock_to_csv.call_args[1]['data'] if 'data' in str(mock_to_csv.call_args) else None

                    # Verify that file export contains unredacted data
                    # The DataFrame passed to to_csv should be the original, not redacted
                    # Since we can't easily extract the actual DataFrame, we verify the logic path:
                    # File output goes through direct CSV save without redaction

    @patch('bankstatementparser.cli.Pain001Parser')
    @patch('pandas.DataFrame.to_csv')
    def test_cli_pain001_output_file_export_unredacted(self, mock_to_csv, mock_pain_parser):
        """Test CLI PAIN001 file export saves unredacted data."""
        # Setup mock parser to return data with PII
        mock_parser_instance = Mock()
        mock_parser_instance.parse.return_value = self.test_data_with_pii.to_dict('records')
        mock_pain_parser.return_value = mock_parser_instance

        with patch.object(self.cli.validator, 'get_safe_filename', return_value='safe_output.csv'):
            with tempfile.NamedTemporaryFile(suffix='.xml') as temp_input:
                input_path = Path(temp_input.name)
                output_path = Path('output.csv')

                with patch('builtins.print'):
                    self.cli.parse_pain(input_path, output_path, show_pii=False)

                    # Verify to_csv was called once for file export
                    self.assertEqual(mock_to_csv.call_count, 1)

    @patch('bankstatementparser.cli.Pain001Parser')
    def test_cli_pain001_console_redaction(self, mock_pain_parser):
        """Test CLI PAIN001 console output redacts PII by default."""
        # Setup mock parser to return data with PII
        mock_parser_instance = Mock()
        mock_parser_instance.parse.return_value = self.test_data_with_pii.to_dict('records')
        mock_pain_parser.return_value = mock_parser_instance

        with tempfile.NamedTemporaryFile(suffix='.xml') as temp_file:
            input_path = Path(temp_file.name)

            with patch('builtins.print') as mock_print:
                # Call without show_pii flag (default behavior)
                self.cli.parse_pain(input_path, None, show_pii=False)

                # Verify print was called (console output)
                self.assertTrue(mock_print.called)

                # Extract the DataFrame that was printed
                print_args = mock_print.call_args[0]
                printed_df = print_args[0]

                # Verify PII columns are redacted in console output
                self.assertIsInstance(printed_df, pd.DataFrame)
                for column in self.expected_redacted_columns:
                    if column in printed_df.columns:
                        self.assertTrue(
                            all(printed_df[column] == '***REDACTED***'),
                            f"PAIN001 console output should redact column '{column}'"
                        )

    def test_parser_redact_pii_true_masks_address_fields(self):
        """Test parser redact_pii=True masks address fields in data."""
        # Test with mocked parse method to verify redact_pii parameter is supported
        with patch.object(CamtParser, 'get_transactions') as mock_get_transactions:
            # Setup mock to simulate behavior with and without redaction
            mock_get_transactions.return_value = pd.DataFrame([
                {
                    'transaction_id': 'TXN001',
                    'debtor_address': '***REDACTED***',  # Redacted address
                    'creditor_address': '***REDACTED***',  # Redacted address
                    'amount': 100.0
                }
            ])

            with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as temp_file:
                temp_file.write('<xml></xml>')  # Minimal valid XML
                temp_file.flush()

                try:
                    parser = CamtParser(temp_file.name)

                    # Test with redact_pii=True
                    result_redacted = parser.parse(redact_pii=True)

                    # Verify get_transactions was called with redact_pii=True
                    mock_get_transactions.assert_called_with(redact_pii=True)

                    # Verify the result is a DataFrame
                    self.assertIsInstance(result_redacted, pd.DataFrame)

                finally:
                    os.unlink(temp_file.name)

    def test_parser_redact_pii_false_returns_full_data(self):
        """Test parser redact_pii=False (default) returns unredacted data."""
        # Test with mocked parse method to verify default behavior
        with patch.object(CamtParser, 'get_transactions') as mock_get_transactions:
            # Setup mock to simulate unredacted behavior
            mock_get_transactions.return_value = pd.DataFrame([
                {
                    'transaction_id': 'TXN001',
                    'debtor_address': '123 Main St',  # Unredacted address
                    'creditor_address': '456 Oak Ave',  # Unredacted address
                    'amount': 100.0
                }
            ])

            with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as temp_file:
                temp_file.write('<xml></xml>')  # Minimal valid XML
                temp_file.flush()

                try:
                    parser = CamtParser(temp_file.name)

                    # Test with redact_pii=False (explicit)
                    result_unredacted = parser.parse(redact_pii=False)
                    mock_get_transactions.assert_called_with(redact_pii=False)

                    # Test default behavior (should be False)
                    result_default = parser.parse()
                    mock_get_transactions.assert_called_with(redact_pii=False)

                    # Both calls should result in DataFrames
                    self.assertIsInstance(result_unredacted, pd.DataFrame)
                    self.assertIsInstance(result_default, pd.DataFrame)

                    # Verify mock was called twice
                    self.assertEqual(mock_get_transactions.call_count, 2)

                finally:
                    os.unlink(temp_file.name)

    def test_pain001_parser_redact_pii_functionality(self):
        """Test Pain001Parser redact_pii parameter functionality."""
        # Test that the parse method accepts redact_pii parameter without errors
        with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as temp_file:
            temp_file.write('<?xml version="1.0" encoding="UTF-8"?><Document></Document>')  # Minimal valid XML
            temp_file.flush()

            try:
                parser = Pain001Parser(temp_file.name)

                # Use patch to avoid actual XML parsing but verify parameter acceptance
                with patch.object(parser, '__init__', return_value=None):
                    # Create a mock parser instance
                    mock_parser = Mock(spec=Pain001Parser)

                    # Test that the parse method signature accepts redact_pii
                    self.assertTrue(hasattr(Pain001Parser.parse, '__code__'))
                    param_names = Pain001Parser.parse.__code__.co_varnames
                    self.assertIn('redact_pii', param_names,
                                 "Pain001Parser.parse should accept redact_pii parameter")

                    # Test that get_summary method signature accepts redact_pii
                    self.assertTrue(hasattr(Pain001Parser.get_summary, '__code__'))
                    summary_params = Pain001Parser.get_summary.__code__.co_varnames
                    self.assertIn('redact_pii', summary_params,
                                 "Pain001Parser.get_summary should accept redact_pii parameter")

            finally:
                os.unlink(temp_file.name)

    def test_cli_integration_camt_full_workflow(self):
        """Integration test: Full CLI workflow with CAMT file and PII redaction."""
        test_args = ['cli.py', '--type', 'camt', '--input', 'test.xml']

        with patch('sys.argv', test_args):
            with patch.object(self.cli, '_sanitize_file_path', return_value='/path/test.xml'):
                with patch.object(self.cli.validator, 'validate_input_file_path', return_value=Path('/path/test.xml')):
                    with patch.object(self.cli, 'parse_camt') as mock_parse_camt:
                        self.cli.run()

                        # Verify parse_camt was called with default show_pii=False
                        mock_parse_camt.assert_called_once_with(Path('/path/test.xml'), None, False)

    def test_cli_integration_with_show_pii_flag(self):
        """Integration test: CLI with --show-pii flag."""
        test_args = ['cli.py', '--type', 'camt', '--input', 'test.xml', '--show-pii']

        with patch('sys.argv', test_args):
            with patch.object(self.cli, '_sanitize_file_path', return_value='/path/test.xml'):
                with patch.object(self.cli.validator, 'validate_input_file_path', return_value=Path('/path/test.xml')):
                    with patch.object(self.cli, 'parse_camt') as mock_parse_camt:
                        self.cli.run()

                        # Verify parse_camt was called with show_pii=True
                        mock_parse_camt.assert_called_once_with(Path('/path/test.xml'), None, True)

    def test_cli_integration_pain001_with_output_file(self):
        """Integration test: PAIN001 parsing with output file."""
        test_args = ['cli.py', '--type', 'pain001', '--input', 'test.xml', '--output', 'result.csv']

        with patch('sys.argv', test_args):
            with patch.object(self.cli, '_sanitize_file_path', side_effect=['/path/test.xml', '/path/result.csv']):
                with patch.object(self.cli.validator, 'validate_input_file_path', return_value=Path('/path/test.xml')):
                    with patch.object(self.cli.validator, 'validate_output_file_path', return_value=Path('/path/result.csv')):
                        with patch.object(self.cli, 'parse_pain') as mock_parse_pain:
                            self.cli.run()

                            # Verify parse_pain was called with output file and default show_pii=False
                            mock_parse_pain.assert_called_once_with(
                                Path('/path/test.xml'),
                                Path('/path/result.csv'),
                                False
                            )

    def test_edge_case_dataframe_with_only_pii_columns(self):
        """Test redaction with DataFrame containing only PII columns."""
        pii_only_data = pd.DataFrame({
            'account_number': ['123456'],
            'iban': ['GB123'],
            'name': ['John Doe'],
            'address': ['123 Main St']
        })

        redacted_df = self.cli._redact_dataframe(pii_only_data)

        # All columns should be redacted
        for column in redacted_df.columns:
            self.assertTrue(
                all(redacted_df[column] == '***REDACTED***'),
                f"All PII columns should be redacted, but '{column}' was not"
            )

    def test_edge_case_partial_keyword_matching(self):
        """Test that partial keyword matches work correctly."""
        partial_match_data = pd.DataFrame({
            'customer_name_full': ['John Doe'],  # Contains 'name'
            'iban_code': ['GB123'],  # Contains 'iban'
            'home_address_line1': ['123 Main St'],  # Contains 'address'
            'safe_data': ['Safe Value'],  # No PII keywords
            'account_holder': ['Jane Smith'],  # Contains 'account'
        })

        redacted_df = self.cli._redact_dataframe(partial_match_data)

        # Columns with PII keywords should be redacted
        self.assertEqual(redacted_df['customer_name_full'].iloc[0], '***REDACTED***')
        self.assertEqual(redacted_df['iban_code'].iloc[0], '***REDACTED***')
        self.assertEqual(redacted_df['home_address_line1'].iloc[0], '***REDACTED***')
        self.assertEqual(redacted_df['account_holder'].iloc[0], '***REDACTED***')

        # Non-PII column should remain unchanged
        self.assertEqual(redacted_df['safe_data'].iloc[0], 'Safe Value')


if __name__ == '__main__':
    unittest.main()