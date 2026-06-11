import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from bankstatementparser import (
    CamtParser,
    CsvStatementParser,
    Mt940Parser,
    OfxParser,
    Pain001Parser,
    QfxParser,
    create_parser,
    detect_statement_format,
)
from bankstatementparser.additional_parsers import (
    _amount_or_zero,
    _parse_amount,
)
from bankstatementparser.input_validator import (
    InputValidator,
    ValidationError,
)


class TestAdditionalParsers(unittest.TestCase):
    def setUp(self):
        self.test_data = Path(__file__).parent / "test_data"
        self.csv_file = self.test_data / "sample_statement.csv"
        self.csv_split_file = self.test_data / "sample_split_amounts.csv"
        self.ofx_file = self.test_data / "sample.ofx"
        self.qfx_file = self.test_data / "sample.qfx"
        self.mt940_file = self.test_data / "sample.mt940"
        self.camt_file = self.test_data / "camt.053.001.02.xml"
        self.pain_file = self.test_data / "pain.001.001.03.xml"

    def test_input_validator_accepts_new_extensions(self):
        validator = InputValidator()
        self.assertEqual(
            validator.validate_input_file_path(str(self.csv_file)),
            self.csv_file.resolve(),
        )
        self.assertEqual(
            validator.validate_input_file_path(str(self.ofx_file)),
            self.ofx_file.resolve(),
        )
        self.assertEqual(
            validator.validate_input_file_path(str(self.mt940_file)),
            self.mt940_file.resolve(),
        )

    def test_csv_parser_normalizes_direct_amount_columns(self):
        parser = CsvStatementParser(self.csv_file)
        df = parser.parse()
        summary = parser.get_summary()
        cached = parser.parse()

        self.assertEqual(df["description"].tolist(), ["Salary", "Rent"])
        self.assertEqual(df["amount"].tolist(), [2500.0, -1200.0])
        self.assertEqual(summary["account_id"], "DE123456789")
        self.assertEqual(summary["transaction_count"], 2)
        self.assertEqual(summary["closing_balance"], 3800.0)
        self.assertEqual(df.to_dict("records"), cached.to_dict("records"))

    def test_csv_parser_builds_amount_from_credit_and_debit(self):
        parser = CsvStatementParser(self.csv_split_file)
        df = parser.parse()
        summary = parser.get_summary()

        self.assertEqual(
            df["amount"].tolist(),
            [Decimal("1250.50"), Decimal("-200.25")],
        )
        self.assertEqual(df["currency"].tolist(), ["EUR", "EUR"])
        self.assertEqual(summary["opening_balance"], 2250.5)
        self.assertEqual(summary["total_amount"], 1050.25)

    def test_ofx_and_qfx_parsers(self):
        ofx_parser = OfxParser(self.ofx_file)
        ofx_df = ofx_parser.parse()
        ofx_summary = ofx_parser.get_summary()

        qfx_parser = QfxParser(self.qfx_file)
        qfx_df = qfx_parser.parse()
        qfx_summary = qfx_parser.get_summary()

        self.assertEqual(ofx_df["transaction_id"].tolist(), ["OFX-1", "OFX-2"])
        self.assertEqual(ofx_summary["currency"], "EUR")
        self.assertEqual(qfx_df["description"].tolist(), ["Morning coffee"])
        self.assertEqual(qfx_summary["total_amount"], -15.0)

    def test_mt940_parser(self):
        parser = Mt940Parser(self.mt940_file)
        df = parser.parse()
        summary = parser.get_summary()

        self.assertEqual(
            df["description"].tolist(), ["Salary payment", "Groceries"]
        )
        self.assertEqual(
            df["amount"].tolist(),
            [Decimal("1250.50"), Decimal("-80.25")],
        )
        self.assertEqual(summary["account_id"], "NL91ABNA0417164300")
        self.assertEqual(summary["opening_balance"], 1000.0)
        self.assertEqual(summary["closing_balance"], 2170.25)

    def test_detect_statement_format_and_factory(self):
        self.assertEqual(detect_statement_format(self.csv_file), "csv")
        self.assertEqual(detect_statement_format(self.ofx_file), "ofx")
        self.assertEqual(detect_statement_format(self.qfx_file), "ofx")
        self.assertEqual(detect_statement_format(self.mt940_file), "mt940")
        self.assertEqual(detect_statement_format(self.camt_file), "camt")
        self.assertEqual(detect_statement_format(self.pain_file), "pain001")

        self.assertIsInstance(create_parser(self.csv_file), CsvStatementParser)
        self.assertIsInstance(create_parser(self.ofx_file), OfxParser)
        self.assertIsInstance(create_parser(self.mt940_file), Mt940Parser)
        self.assertIsInstance(create_parser(self.camt_file), CamtParser)
        self.assertIsInstance(create_parser(self.pain_file), Pain001Parser)
        self.assertIsInstance(create_parser(self.qfx_file, "qfx"), QfxParser)

    def test_factory_rejects_unknown_and_detection_rejects_unknown(
        self,
    ):
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write("<Document><Unknown/></Document>")
            unknown_file = Path(handle.name)

        try:
            with self.assertRaises(ValidationError):
                detect_statement_format(unknown_file)
            with self.assertRaises(ValidationError):
                create_parser(self.csv_file, "bogus")
        finally:
            unknown_file.unlink(missing_ok=True)

    def test_parse_amount_helper_covers_supported_number_formats(self):
        self.assertIsNone(_parse_amount(None))
        self.assertIsNone(_parse_amount(""))
        self.assertIsNone(_parse_amount("bad"))
        self.assertEqual(_parse_amount("1234.56"), Decimal("1234.56"))
        self.assertEqual(_parse_amount("1,234.56"), Decimal("1234.56"))
        self.assertEqual(_parse_amount("1.234,56"), Decimal("1234.56"))
        self.assertEqual(_parse_amount("123,45"), Decimal("123.45"))

    def test_detection_falls_back_to_content_signatures(self):
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", encoding="utf-8", delete=False
        ) as ofx_handle:
            ofx_handle.write("<root><OFX><BANKTRANLIST/></OFX></root>")
            ofx_path = Path(ofx_handle.name)
        with tempfile.NamedTemporaryFile(
            suffix=".xml", mode="w", encoding="utf-8", delete=False
        ) as mt940_handle:
            mt940_handle.write(":20:ABC\n:61:260320C10,00REF")
            mt940_path = Path(mt940_handle.name)

        try:
            self.assertEqual(detect_statement_format(ofx_path), "ofx")
            self.assertEqual(detect_statement_format(mt940_path), "mt940")
        finally:
            ofx_path.unlink(missing_ok=True)
            mt940_path.unlink(missing_ok=True)

    def test_empty_csv_and_missing_ofx_tag_paths(self):
        with tempfile.NamedTemporaryFile(
            suffix=".csv", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write("Date,Amount\n")
            csv_path = Path(handle.name)
        try:
            csv_parser = CsvStatementParser(csv_path)
            csv_summary = csv_parser.get_summary()
            self.assertEqual(csv_summary["transaction_count"], 0)
            self.assertIsNone(csv_summary["account_id"])
        finally:
            csv_path.unlink(missing_ok=True)

        ofx_parser = OfxParser(self.ofx_file)
        self.assertIsNone(ofx_parser._tag_value(ofx_parser._text, "MISSING"))

    def test_csv_without_date_column_and_malformed_mt940_lines(self):
        with tempfile.NamedTemporaryFile(
            suffix=".csv", mode="w", encoding="utf-8", delete=False
        ) as csv_handle:
            csv_handle.write("Description,Amount\nFee,-12.34\n")
            csv_path = Path(csv_handle.name)
        with tempfile.NamedTemporaryFile(
            suffix=".mt940", mode="w", encoding="utf-8", delete=False
        ) as mt940_handle:
            mt940_handle.write(
                ":20:REF\n"
                ":25:ACCOUNT\n"
                ":60F:INVALID\n"
                ":61:INVALID\n"
                ":86:Ignored description\n"
            )
            mt940_path = Path(mt940_handle.name)

        try:
            csv_parser = CsvStatementParser(csv_path)
            csv_summary = csv_parser.get_summary()
            self.assertIsNone(csv_summary["statement_date"])

            mt940_parser = Mt940Parser(mt940_path)
            mt940_df = mt940_parser.parse()
            mt940_summary = mt940_parser.get_summary()
            self.assertTrue(mt940_df.empty)
            self.assertEqual(mt940_summary["transaction_count"], 0)
            self.assertEqual(mt940_summary["account_id"], "ACCOUNT")
        finally:
            csv_path.unlink(missing_ok=True)
            mt940_path.unlink(missing_ok=True)

    def test_non_utf8_file_raises_validation_error(self):
        # InputValidator only checks the first 1KB for UTF-8, so the
        # invalid bytes must sit past that header to exercise the
        # full-file decode guard in _read_validated_text.
        with tempfile.NamedTemporaryFile(
            suffix=".csv", mode="wb", delete=False
        ) as handle:
            handle.write(b"Date,Description,Amount\n")
            handle.write(b"2024-01-01,Fee,-1.00\n" * 60)
            handle.write(b"2024-01-02,\x80\x81bad,-2.00\n")
            bad_path = Path(handle.name)
        try:
            with self.assertRaisesRegex(
                ValidationError, "File is not valid UTF-8"
            ):
                CsvStatementParser(bad_path)
        finally:
            bad_path.unlink(missing_ok=True)

    def test_amount_or_zero_blank_string_is_zero(self):
        self.assertEqual(_amount_or_zero("   ", context="test"), Decimal("0"))
