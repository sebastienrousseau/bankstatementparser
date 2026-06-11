import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bankstatementparser.cli import BankStatementCLI, main
from bankstatementparser.input_validator import ValidationError


class TestConsoleScript(unittest.TestCase):
    def test_main_delegates_to_cli_run(self):
        """The console-script entry point dispatches to BankStatementCLI.run()."""
        with patch("bankstatementparser.cli.BankStatementCLI") as mock_cls:
            instance = Mock()
            mock_cls.return_value = instance
            main()
            mock_cls.assert_called_once_with()
            instance.run.assert_called_once_with()


class TestBankStatementCLI(unittest.TestCase):
    def setUp(self):
        self.cli = BankStatementCLI()

    def test_init(self):
        """Test CLI initialization."""
        self.assertIsNotNone(self.cli)
        self.assertIsNotNone(self.cli.parser)
        self.assertIsNotNone(self.cli.validator)

    def test_setup_arg_parser(self):
        """Test argument parser setup."""
        parser = self.cli.setup_arg_parser()
        self.assertIsNotNone(parser)

        # Test that required arguments are configured
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    @patch("bankstatementparser.cli.CamtParser")
    @patch("pandas.DataFrame.to_csv")
    def test_parse_camt_success_with_output(
        self, mock_to_csv, mock_camt_parser
    ):
        """Test successful CAMT parsing with output file."""
        # Setup mocks
        mock_parser_instance = Mock()
        mock_parser_instance.get_statement_stats.return_value = [
            {"test": "data"}
        ]
        mock_camt_parser.return_value = mock_parser_instance

        with (
            patch.object(
                self.cli.validator,
                "get_safe_filename",
                return_value="safe_output.csv",
            ),
            tempfile.NamedTemporaryFile(suffix=".xml") as temp_file,
        ):
            input_path = Path(temp_file.name)
            output_path = Path("output.csv")

            with patch("builtins.print") as mock_print:
                self.cli.parse_camt(input_path, output_path)
                mock_to_csv.assert_called_once()
                mock_print.assert_called()

    @patch("bankstatementparser.cli.CamtParser")
    def test_parse_camt_success_no_output(self, mock_camt_parser):
        """Test successful CAMT parsing without output file."""
        # Setup mocks
        mock_parser_instance = Mock()
        mock_parser_instance.get_statement_stats.return_value = {
            "test": "data"
        }
        mock_camt_parser.return_value = mock_parser_instance

        with tempfile.NamedTemporaryFile(suffix=".xml") as temp_file:
            input_path = Path(temp_file.name)

            with patch("builtins.print") as mock_print:
                self.cli.parse_camt(input_path, None)
                self.assertTrue(mock_print.call_count > 0)

    @patch("bankstatementparser.cli.CamtParser")
    def test_parse_camt_file_not_found(self, mock_camt_parser):
        """Test CAMT parsing with file not found error."""
        mock_camt_parser.side_effect = FileNotFoundError("File not found")

        with patch("sys.exit") as mock_exit:
            with patch("builtins.print") as mock_print:
                self.cli.parse_camt(Path("nonexistent.xml"), None)
                mock_exit.assert_called_with(1)
                mock_print.assert_called()

    @patch("bankstatementparser.cli.CamtParser")
    def test_parse_camt_validation_error(self, mock_camt_parser):
        """Test CAMT parsing with validation error."""
        mock_camt_parser.side_effect = ValidationError("Invalid file")

        with patch("sys.exit") as mock_exit:
            with patch("builtins.print") as mock_print:
                self.cli.parse_camt(Path("invalid.xml"), None)
                mock_exit.assert_called_with(1)
                mock_print.assert_called()

    @patch("bankstatementparser.cli.CamtParser")
    def test_parse_camt_general_exception(self, mock_camt_parser):
        """Test CAMT parsing with general exception."""
        mock_camt_parser.side_effect = Exception("Unexpected error")

        with patch("sys.exit") as mock_exit:
            with patch("builtins.print") as mock_print:
                self.cli.parse_camt(Path("error.xml"), None)
                mock_exit.assert_called_with(1)
                mock_print.assert_called()

    @patch("bankstatementparser.cli.Pain001Parser")
    @patch("pandas.DataFrame.to_csv")
    def test_parse_pain_success_with_output(
        self, mock_to_csv, mock_pain_parser
    ):
        """Test successful PAIN parsing with output file."""
        # Setup mocks
        mock_parser_instance = Mock()
        mock_parser_instance.parse.return_value = [{"test": "data"}]
        mock_pain_parser.return_value = mock_parser_instance

        with (
            patch.object(
                self.cli.validator,
                "get_safe_filename",
                return_value="safe_output.csv",
            ),
            tempfile.NamedTemporaryFile(suffix=".xml") as temp_file,
        ):
            input_path = Path(temp_file.name)
            output_path = Path("output.csv")

            with patch("builtins.print") as mock_print:
                self.cli.parse_pain(input_path, output_path)
                mock_to_csv.assert_called_once()
                mock_print.assert_called()

    @patch("bankstatementparser.cli.Pain001Parser")
    def test_parse_pain_success_no_output(self, mock_pain_parser):
        """Test successful PAIN parsing without output file."""
        # Setup mocks
        mock_parser_instance = Mock()
        mock_parser_instance.parse.return_value = [{"test": "data"}]
        mock_pain_parser.return_value = mock_parser_instance

        with tempfile.NamedTemporaryFile(suffix=".xml") as temp_file:
            input_path = Path(temp_file.name)

            with patch("builtins.print") as mock_print:
                self.cli.parse_pain(input_path, None)
                self.assertTrue(mock_print.call_count > 0)

    @patch("bankstatementparser.cli.Pain001Parser")
    def test_parse_pain_file_not_found(self, mock_pain_parser):
        """Test PAIN parsing with file not found error."""
        mock_pain_parser.side_effect = FileNotFoundError("File not found")

        with patch("sys.exit") as mock_exit:
            with patch("builtins.print") as mock_print:
                self.cli.parse_pain(Path("nonexistent.xml"), None)
                mock_exit.assert_called_with(1)
                mock_print.assert_called()

    @patch("bankstatementparser.cli.Pain001Parser")
    def test_parse_pain_validation_error(self, mock_pain_parser):
        """Test PAIN parsing with validation error."""
        mock_pain_parser.side_effect = ValidationError("Invalid file")

        with patch("sys.exit") as mock_exit:
            with patch("builtins.print") as mock_print:
                self.cli.parse_pain(Path("invalid.xml"), None)
                mock_exit.assert_called_with(1)
                mock_print.assert_called()

    @patch("bankstatementparser.cli.Pain001Parser")
    def test_parse_pain_general_exception(self, mock_pain_parser):
        """Test PAIN parsing with general exception."""
        mock_pain_parser.side_effect = Exception("Unexpected error")

        with patch("sys.exit") as mock_exit:
            with patch("builtins.print") as mock_print:
                self.cli.parse_pain(Path("error.xml"), None)
                mock_exit.assert_called_with(1)
                mock_print.assert_called()

    @patch("sys.argv", ["cli.py"])
    def test_run_no_args(self):
        """Test run with no arguments."""
        with patch("sys.exit") as mock_exit:
            self.cli.run()
            mock_exit.assert_called_with(1)

    @patch("sys.argv", ["cli.py", "--type", "camt", "--input", "test.xml"])
    @patch("bankstatementparser.cli.logger")
    def test_run_camt_success(self, mock_logger):
        """Test successful CAMT parsing via run method."""
        with (
            patch.object(
                self.cli.validator,
                "validate_input_file_path",
                return_value=Path("/path/test.xml"),
            ),
            patch.object(self.cli, "parse_camt") as mock_parse,
        ):
            self.cli.run()
            mock_parse.assert_called_once_with(
                Path("/path/test.xml"), None, False
            )

    @patch(
        "sys.argv",
        ["cli.py", "--type", "pain001", "--input", "test.xml"],
    )
    @patch("bankstatementparser.cli.logger")
    def test_run_pain001_success(self, mock_logger):
        """Test successful PAIN001 parsing via run method."""
        with (
            patch.object(
                self.cli.validator,
                "validate_input_file_path",
                return_value=Path("/path/test.xml"),
            ),
            patch.object(self.cli, "parse_pain") as mock_parse,
        ):
            self.cli.run()
            mock_parse.assert_called_once_with(
                Path("/path/test.xml"), None, False
            )

    @patch(
        "sys.argv",
        [
            "cli.py",
            "--type",
            "camt",
            "--input",
            "test.xml",
            "--output",
            "output.csv",
        ],
    )
    @patch("bankstatementparser.cli.logger")
    def test_run_with_output_success(self, mock_logger):
        """Test successful parsing with output file via run method."""
        with (
            patch.object(
                self.cli.validator,
                "validate_input_file_path",
                return_value=Path("/path/test.xml"),
            ),
            patch.object(
                self.cli.validator,
                "validate_output_file_path",
                return_value=Path("/path/output.csv"),
            ),
            patch.object(self.cli, "parse_camt") as mock_parse,
        ):
            self.cli.run()
            mock_parse.assert_called_with(
                Path("/path/test.xml"),
                Path("/path/output.csv"),
                False,
            )

    @patch(
        "sys.argv",
        [
            "cli.py",
            "--type",
            "camt",
            "--input",
            "test.xml",
            "--max-size",
            "50",
        ],
    )
    @patch("bankstatementparser.cli.logger")
    def test_run_with_max_size(self, mock_logger):
        """Test run with custom max size parameter."""
        with (
            patch.object(
                self.cli.validator,
                "validate_input_file_path",
                return_value=Path("/path/test.xml"),
            ),
            patch.object(self.cli, "parse_camt") as mock_parse,
        ):
            self.cli.run()
            # Verify validator was updated with new size
            self.assertEqual(
                self.cli.validator.max_file_size,
                50 * 1024 * 1024,
            )
            mock_parse.assert_called_once()

    @patch(
        "sys.argv",
        ["cli.py", "--type", "camt", "--input", "invalid.xml"],
    )
    def test_run_input_validation_failed(self):
        """Test run with input validation failure."""
        with (
            patch.object(
                self.cli.validator,
                "validate_input_file_path",
                side_effect=ValidationError("Invalid path"),
            ),
            patch("sys.exit") as mock_exit,
        ):
            with patch("builtins.print") as mock_print:
                self.cli.run()
                mock_exit.assert_called_with(1)
                mock_print.assert_called()

    @patch(
        "sys.argv",
        [
            "cli.py",
            "--type",
            "camt",
            "--input",
            "test.xml",
            "--output",
            "invalid.csv",
        ],
    )
    def test_run_output_validation_failed(self):
        """Test run with output validation failure."""
        with (
            patch.object(
                self.cli.validator,
                "validate_input_file_path",
                return_value=Path("/path/test.xml"),
            ),
            patch.object(
                self.cli.validator,
                "validate_output_file_path",
                side_effect=ValidationError("Invalid output"),
            ),
            patch("sys.exit") as mock_exit,
        ):
            with patch("builtins.print") as mock_print:
                self.cli.run()
                mock_exit.assert_called_with(1)
                mock_print.assert_called()

    @patch(
        "sys.argv",
        ["cli.py", "--type", "unsupported", "--input", "test.xml"],
    )
    def test_run_unsupported_type(self):
        """Test run with unsupported file type."""
        with (
            patch.object(
                self.cli.validator,
                "validate_input_file_path",
                return_value=Path("/path/test.xml"),
            ),
            patch("sys.exit") as mock_exit,
        ):
            with patch("builtins.print") as mock_print:
                self.cli.run()
                mock_exit.assert_called_with(1)
                mock_print.assert_called()

    @patch("sys.argv", ["cli.py", "--type", "camt", "--input", "test.xml"])
    def test_run_parsing_exception(self):
        """Test run with parsing exception."""
        with (
            patch.object(
                self.cli.validator,
                "validate_input_file_path",
                return_value=Path("/path/test.xml"),
            ),
            patch.object(
                self.cli,
                "parse_camt",
                side_effect=Exception("Parse error"),
            ),
            patch("sys.exit") as mock_exit,
        ):
            with patch("builtins.print") as mock_print:
                self.cli.run()
                mock_exit.assert_called_with(1)
                mock_print.assert_called()


if __name__ == "__main__":
    unittest.main()
