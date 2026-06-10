"""
Focused tests for remaining error branches and CLI automation paths.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from bankstatementparser.base_parser import BankStatementParser
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.cli import BankStatementCLI
from bankstatementparser.input_validator import (
    InputValidator,
    ValidationError,
)
from bankstatementparser.pain001_parser import Pain001Parser


class DummyParser(BankStatementParser):
    def __init__(self, file_name="dummy.xml", df=None, summary=None):
        super().__init__(file_name)
        self._df = df if df is not None else pd.DataFrame([{"a": 1}])
        self._summary = (
            summary
            if summary is not None
            else {
                "account_id": "ACC",
                "transaction_count": 1,
            }
        )

    def parse(self):
        return self._df

    def get_summary(self):
        return self._summary


class ExplodingSummaryParser(DummyParser):
    def get_summary(self):
        raise RuntimeError("boom")


class TestBaseParserCoverage(unittest.TestCase):
    def test_export_csv_cleanup_on_parse_failure(self):
        parser = DummyParser()
        output = Path(tempfile.gettempdir()) / "broken-export.csv"
        temp_output = Path(f"{output}.tmp")

        with patch.object(
            parser, "parse", side_effect=RuntimeError("x")
        ):
            with self.assertRaises(OSError):
                parser.export_csv(output)

        self.assertFalse(temp_output.exists())

    def test_export_json_cleanup_on_summary_failure(self):
        parser = DummyParser()
        output = Path(tempfile.gettempdir()) / "broken-export.json"
        temp_output = Path(f"{output}.tmp")

        with patch.object(
            parser, "get_summary", side_effect=RuntimeError("x")
        ):
            with self.assertRaises(OSError):
                parser.export_json(output)

        self.assertFalse(temp_output.exists())

    def test_str_fallback_on_summary_error(self):
        parser = ExplodingSummaryParser("broken.xml")
        self.assertEqual(
            str(parser), "ExplodingSummaryParser(file='broken.xml')"
        )

    def test_abstract_methods_pass_lines(self):
        parser = DummyParser()
        self.assertIsNone(BankStatementParser.parse(parser))
        self.assertIsNone(BankStatementParser.get_summary(parser))


class TestInputValidatorCoverage(unittest.TestCase):
    def setUp(self):
        self.validator = InputValidator()

    def test_symlink_target_outside_parent_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = tempfile.mkdtemp()
            target_file = Path(target_dir) / "target.xml"
            target_file.write_text(
                "<?xml version='1.0'?><Document></Document>"
            )
            link_path = Path(tmpdir) / "link.xml"
            link_path.symlink_to(target_file)

            with self.assertRaises(ValidationError):
                self.validator.validate_input_file_path(str(link_path))

    def test_sanitize_source_name_none_and_invalid_type(self):
        self.assertEqual(
            self.validator.sanitize_source_name(None), "<memory>"
        )
        with self.assertRaises(ValidationError):
            self.validator.sanitize_source_name(123)

    def test_validate_xml_content_empty_and_invalid_type(self):
        with self.assertRaises(ValidationError):
            self.validator.validate_xml_content("")
        with self.assertRaises(ValidationError):
            self.validator.validate_xml_content(b"")
        with self.assertRaises(ValidationError):
            self.validator.validate_xml_content(123)

    def test_validate_bytes_size_zero(self):
        with self.assertRaises(ValidationError):
            self.validator._validate_bytes_size(b"")

    def test_validate_file_size_stat_error(self):
        with patch("pathlib.Path.stat", side_effect=OSError("boom")):
            with self.assertRaises(ValidationError):
                self.validator._validate_file_size(Path("x.xml"))

    def test_validate_input_format_binary_control_chars(self):
        with tempfile.NamedTemporaryFile(
            suffix=".xml", delete=False
        ) as f:
            f.write(b"Hello\x00World")
            path = f.name
        try:
            with self.assertRaises(ValidationError):
                self.validator._validate_input_format(Path(path))
        finally:
            os.unlink(path)

    def test_validate_input_format_oserror(self):
        with patch("builtins.open", side_effect=OSError("boom")):
            with self.assertRaises(ValidationError):
                self.validator._validate_input_format(Path("x.xml"))

    def test_validate_xml_bytes_format_warning_path(self):
        with patch(
            "bankstatementparser.input_validator.logger.warning"
        ) as warn:
            self.validator._validate_xml_bytes_format(
                b"plain text but not xml", "source.xml"
            )
            warn.assert_called_once()

    def test_validate_xml_bytes_format_binary_control_chars(self):
        with self.assertRaises(ValidationError):
            self.validator._validate_xml_bytes_format(
                b"Hello\x00World", "source.xml"
            )

    def test_check_dangerous_patterns_unicode_control(self):
        with self.assertRaises(ValidationError):
            self.validator._check_dangerous_patterns(
                "unsafe\u202epath.xml"
            )

    def test_validate_input_format_binary_signature(self):
        with tempfile.NamedTemporaryFile(
            suffix=".xml", delete=False
        ) as f:
            f.write(b"%PDF-1.7")
            path = f.name
        try:
            with self.assertRaises(ValidationError):
                self.validator._validate_input_format(Path(path))
        finally:
            os.unlink(path)

    def test_validate_xml_bytes_format_invalid_utf8(self):
        with self.assertRaises(ValidationError):
            self.validator._validate_xml_bytes_format(
                b"\xff\xfe\xfd", "source.xml"
            )


class TestCamtParserCoverageExtra(unittest.TestCase):
    def setUp(self):
        self.camt_file = (
            Path(__file__).parent / "test_data" / "camt.053.001.02.xml"
        )

    def test_malformed_statement_structure_raises(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt><Stmt><Weird>value</Weird></Stmt></BkToCstmrStmt>
</Document>"""
        parser = CamtParser.from_string(xml, source_name="weird.xml")
        with self.assertRaises(ValueError):
            parser.get_account_balances()

    def test_get_transactions_redacts_only_present_addresses(self):
        parser = CamtParser.from_string(
            """<?xml version="1.0" encoding="UTF-8"?>
            <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
              <BkToCstmrStmt><Stmt>
                <Acct><Id><IBAN>DE123</IBAN></Id></Acct>
                <Ntry>
                  <Amt Ccy="EUR">10.00</Amt>
                  <CdtDbtInd>CRDT</CdtDbtInd>
                  <ValDt><Dt>2024-01-01</Dt></ValDt>
                  <BookgDt><Dt>2024-01-01</Dt></BookgDt>
                  <NtryDtls><TxDtls><RltdPties>
                    <Dbtr><Nm>A</Nm><PstlAdr><AdrLine>One</AdrLine></PstlAdr></Dbtr>
                    <Cdtr><Nm>B</Nm><PstlAdr><AdrLine>Two</AdrLine></PstlAdr></Cdtr>
                  </RltdPties></TxDtls></NtryDtls>
                </Ntry>
              </Stmt></BkToCstmrStmt>
            </Document>""",
            source_name="redaction.xml",
        )
        results = parser.get_transactions(redact_pii=True)
        self.assertTrue(
            all(
                val == "***REDACTED***"
                for val in results["DebtorAddress"].dropna()
            )
        )

    def test_streaming_transaction_redaction_and_dttm_fallback(self):
        parser = CamtParser(str(self.camt_file))
        tx = next(parser.parse_streaming(redact_pii=True))
        self.assertIn("BookgDt", tx)
        self.assertTrue(tx["BookgDt"])

    def test_streaming_propagates_per_row_error(self):
        """R-007: streaming must fail-fast on per-row parse errors.

        The previous behaviour was to log a warning and ``continue``,
        which silently dropped malformed transactions from the stream
        — directly contradicting the R-007 control in the risk
        register and the equivalent PAIN.001 streaming behaviour.
        """
        parser = CamtParser(str(self.camt_file))
        with patch.object(
            parser,
            "_parse_streaming_transaction",
            side_effect=RuntimeError("broken"),
        ):
            with patch(
                "bankstatementparser.camt_parser.logger.error"
            ) as err:
                with self.assertRaises(RuntimeError):
                    list(parser.parse_streaming())
                err.assert_called()

    def test_streaming_transaction_valdt_dttm_fallback_and_missing_booking(
        self,
    ):
        entry = CamtParser.from_string(
            """<?xml version="1.0" encoding="UTF-8"?>
            <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
              <BkToCstmrStmt><Stmt><Ntry>
                <Amt Ccy="EUR">10.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><DtTm>2024-01-01T00:00:00</DtTm></ValDt>
              </Ntry></Stmt></BkToCstmrStmt>
            </Document>""",
            source_name="entry.xml",
        )
        tx = next(entry.parse_streaming())
        self.assertEqual(tx["ValDt"], "2024-01-01T00:00:00")
        self.assertEqual(tx["BookgDt"], "")


class TestPain001CoverageExtra(unittest.TestCase):
    def setUp(self):
        self.pain_file = (
            Path(__file__).parent / "test_data" / "pain.001.001.03.xml"
        )

    def test_init_rewraps_format_validation_read_error(self):
        with patch.object(
            InputValidator,
            "validate_input_file_path",
            side_effect=ValidationError(
                "Cannot read file for format validation: denied"
            ),
        ):
            with self.assertRaises(ValidationError) as ctx:
                Pain001Parser("foo.xml")
        self.assertIn("Error reading file: denied", str(ctx.exception))

    def test_init_open_generic_error(self):
        with patch.object(
            InputValidator,
            "validate_input_file_path",
            return_value=Path("foo.xml"),
        ):
            with patch("builtins.open", side_effect=OSError("disk")):
                with self.assertRaises(ValidationError):
                    Pain001Parser("foo.xml")

    def test_parse_streaming_validation_error(self):
        parser = Pain001Parser(str(self.pain_file))
        parser.file_name = "bad.xml"
        with patch.object(
            InputValidator,
            "validate_input_file_path",
            side_effect=ValidationError("bad"),
        ):
            with self.assertRaises(ValidationError):
                list(parser.parse_streaming())

    def test_parse_streaming_generic_open_error(self):
        parser = Pain001Parser(str(self.pain_file))
        parser.file_name = Path(self.pain_file)
        with patch("builtins.open", side_effect=OSError("disk")):
            with self.assertRaises(ValidationError):
                list(parser.parse_streaming())

    def test_parse_streaming_error_propagates(self):
        parser = Pain001Parser(str(self.pain_file))
        with patch.object(
            parser,
            "_parse_streaming_payment",
            side_effect=RuntimeError("boom"),
        ):
            with patch("os.unlink", side_effect=OSError("cleanup")):
                with self.assertRaises(RuntimeError):
                    list(parser.parse_streaming())

    def test_parse_streaming_redaction_and_summary_error_fallback(self):
        parser = Pain001Parser(str(self.pain_file))
        first_payment = next(parser.parse_streaming(redact_pii=True))
        self.assertEqual(first_payment["InitgPty"], "***REDACTED***")

        parser.tree = MagicMock()
        parser.tree.getroottree.side_effect = RuntimeError("boom")
        summary = parser.get_summary()
        self.assertEqual(summary["account_id"], "Unknown")
        self.assertIn("error", summary)


class TestCLICoverageExtra(unittest.TestCase):
    def setUp(self):
        self.cli = BankStatementCLI()

    def test_parse_camt_streaming_console_limit_and_show_pii(self):
        parser = MagicMock()
        parser.parse_streaming.return_value = (
            {"AccountId": "1", "Name": "x"} for _ in range(101)
        )
        with patch(
            "bankstatementparser.cli.CamtParser", return_value=parser
        ):
            with patch("builtins.print") as mock_print:
                self.cli.parse_camt(
                    Path("x.xml"), None, show_pii=True, streaming=True
                )
        printed = "\n".join(
            str(call.args[0])
            for call in mock_print.call_args_list
            if call.args
        )
        self.assertIn(
            "WARNING: Displaying unredacted PII data", printed
        )
        self.assertIn("showing first 100 transactions", printed)

    def test_parse_pain_streaming_console_limit_and_show_pii(self):
        parser = MagicMock()
        parser.parse_streaming.return_value = (
            {"AccountId": "1", "Name": "x"} for _ in range(101)
        )
        with patch(
            "bankstatementparser.cli.Pain001Parser", return_value=parser
        ):
            with patch("builtins.print") as mock_print:
                self.cli.parse_pain(
                    Path("x.xml"), None, show_pii=True, streaming=True
                )
        printed = "\n".join(
            str(call.args[0])
            for call in mock_print.call_args_list
            if call.args
        )
        self.assertIn(
            "WARNING: Displaying unredacted PII data", printed
        )
        self.assertIn("showing first 100 payments", printed)

    def test_parse_pain_non_stream_output_and_show_pii(self):
        parser = MagicMock()
        parser.parse.return_value = pd.DataFrame([{"Name": "Alice"}])
        with patch(
            "bankstatementparser.cli.Pain001Parser", return_value=parser
        ):
            with patch("builtins.print") as mock_print:
                self.cli.parse_pain(
                    Path("x.xml"), None, show_pii=True, streaming=False
                )
        self.assertTrue(
            any(
                "WARNING: Displaying unredacted PII data"
                in str(c.args[0])
                for c in mock_print.call_args_list
                if c.args
            )
        )

    def test_run_argparse_failure_and_missing_required_and_parse_failure(
        self,
    ):
        with patch.object(
            self.cli.parser, "parse_args", side_effect=SystemExit(2)
        ):
            with (
                patch("builtins.print") as mock_print,
                patch("sys.exit") as mock_exit,
            ):
                self.cli.run()
        self.assertTrue(
            any(
                "Missing required arguments" in str(c.args[0])
                for c in mock_print.call_args_list
                if c.args
            )
        )
        self.assertEqual(mock_exit.call_args_list[-1].args[0], 1)

        args = MagicMock()
        args.type = "camt"
        args.input = None
        args.output = None
        args.max_size = 100
        args.verbose = False
        args.show_pii = False
        args.streaming = False
        with patch.object(
            self.cli.parser, "parse_args", return_value=args
        ):
            with (
                patch("builtins.print") as mock_print,
                patch("sys.exit") as mock_exit,
            ):
                self.cli.run()
        self.assertTrue(
            any(
                "Missing required arguments" in str(c.args[0])
                for c in mock_print.call_args_list
                if c.args
            )
        )
        self.assertEqual(mock_exit.call_args_list[-1].args[0], 1)

        args.input = "x.xml"
        args.type = "unsupported-type"
        with patch.object(
            self.cli.parser, "parse_args", return_value=args
        ):
            with patch.object(
                self.cli.validator,
                "validate_input_file_path",
                return_value=Path("/tmp/x.xml"),
            ):
                with (
                    patch("builtins.print") as mock_print,
                    patch("sys.exit") as mock_exit,
                ):
                    self.cli.run()
        self.assertTrue(
            any(
                "specified type is not supported" in str(c.args[0])
                for c in mock_print.call_args_list
                if c.args
            )
        )
        self.assertEqual(mock_exit.call_args_list[-1].args[0], 1)

        args.type = "camt"
        with patch.object(
            self.cli.parser, "parse_args", return_value=args
        ):
            with patch.object(
                self.cli.validator,
                "validate_input_file_path",
                return_value=Path("/tmp/x.xml"),
            ):
                with patch.object(
                    self.cli,
                    "parse_camt",
                    side_effect=RuntimeError("boom"),
                ):
                    with (
                        patch("builtins.print") as mock_print,
                        patch("sys.exit") as mock_exit,
                    ):
                        self.cli.run()
        self.assertTrue(
            any(
                "Parsing failed" in str(c.args[0])
                for c in mock_print.call_args_list
                if c.args
            )
        )
        self.assertEqual(mock_exit.call_args_list[-1].args[0], 1)
