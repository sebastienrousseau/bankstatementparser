# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for the SWIFT MT942 interim statement parser engine."""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from bankstatementparser import (
    Mt942Parser,
    create_parser,
    detect_statement_format,
)
from bankstatementparser.input_validator import ValidationError


class TestMt942Parser(unittest.TestCase):
    """Test suite for MT942 interim transaction report parser."""

    def setUp(self) -> None:
        """Set up paths to sample MT942 statement files."""
        self.test_data = Path(__file__).parent / "test_data"
        self.sample_file = self.test_data / "sample.mt942"

    def test_parse_sample_file(self) -> None:
        """Verify parsing standard sample MT942 statement."""
        parser = Mt942Parser(self.sample_file)
        df = parser.parse()
        self.assertEqual(len(df), 2)
        self.assertEqual(df["currency"].tolist(), ["EUR", "EUR"])
        self.assertEqual(
            df["account_id"].tolist(),
            ["NL91ABNA0417164300", "NL91ABNA0417164300"],
        )
        self.assertEqual(
            df["description"].tolist(),
            [
                "Interim credit transfer additional details line 2",
                "Debit card purchase",
            ],
        )
        self.assertEqual(df["amount"].iloc[0], Decimal("1250.50"))
        self.assertEqual(df["amount"].iloc[1], Decimal("-80.25"))

        # Cached call
        cached_df = parser.parse()
        self.assertIs(cached_df, df)

        # Summary check
        summary = parser.get_summary()
        self.assertEqual(summary["account_id"], "NL91ABNA0417164300")
        self.assertEqual(summary["currency"], "EUR")
        self.assertEqual(summary["transaction_count"], 2)
        self.assertEqual(summary["total_amount"], Decimal("1170.25"))
        self.assertEqual(summary["opening_balance"], Decimal("100.00"))
        self.assertEqual(summary["statement_date"], "2026-03-20")

    def test_detection_by_suffix_and_content(self) -> None:
        """Test auto-detection of MT942 format by suffix and content."""
        detected = detect_statement_format(self.sample_file)
        self.assertEqual(detected, "mt942")

        parser = create_parser(self.sample_file)
        self.assertIsInstance(parser, Mt942Parser)

        parser_explicit = create_parser(self.sample_file, format_name="mt942")
        self.assertIsInstance(parser_explicit, Mt942Parser)

        # Detect by content with .json extension (not matching any suffix parser)
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            f.write(":34F:EUR100,00\n:61:260320C50,00NTRFNONREF//1\n")
            tmp_path = f.name
        try:
            detected_txt = detect_statement_format(tmp_path)
            self.assertEqual(detected_txt, "mt942")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_floor_limit_parsing_variations(self) -> None:
        """Test debit and credit floor limit parsing and conflict validation."""
        summary = Mt942Parser._empty_summary()

        # Credit floor limit
        Mt942Parser._parse_floor_limit(":34F:USDC1500,50", summary)
        self.assertEqual(summary["currency"], "USD")
        self.assertEqual(summary["opening_balance"], Decimal("1500.50"))

        # Debit floor limit
        summary_debit = Mt942Parser._empty_summary()
        Mt942Parser._parse_floor_limit(":34F:GBPD250,00", summary_debit)
        self.assertEqual(summary_debit["currency"], "GBP")
        self.assertEqual(summary_debit["opening_balance"], Decimal("-250.00"))

        # Conflicting currency error
        with self.assertRaises(ValidationError) as ctx:
            Mt942Parser._parse_floor_limit(":34F:EUR500,00", summary)
        self.assertIn(
            "Conflicting MT942 statement currency", str(ctx.exception)
        )

        # Malformed line
        with self.assertRaises(ValidationError) as ctx:
            Mt942Parser._parse_floor_limit(":34F:INVALID", summary)
        self.assertIn("Malformed MT942 :34F:", str(ctx.exception))

    def test_datetime_indication_parsing(self) -> None:
        """Test :13D: datetime indication and error handling."""
        summary = Mt942Parser._empty_summary()
        Mt942Parser._parse_datetime_indication(":13D:2604150930", summary)
        self.assertEqual(summary["statement_date"], "2026-04-15")

        with self.assertRaises(ValidationError) as ctx:
            Mt942Parser._parse_datetime_indication(":13D:BADTIME", summary)
        self.assertIn("Malformed MT942 :13D:", str(ctx.exception))

    def test_transaction_line_sign_handling(self) -> None:
        """Test transaction parsing for various credit/debit mark variations."""
        summary = Mt942Parser._empty_summary()
        summary["currency"] = "EUR"
        summary["account_id"] = "ACC-01"

        # Reversal Credit (RC) -> negative
        t_rc = Mt942Parser._parse_transaction_line(
            ":61:260320RC100,00NTRF//TX1", summary
        )
        self.assertEqual(t_rc["amount"], Decimal("-100.00"))

        # Reversal Debit (RD) -> positive
        t_rd = Mt942Parser._parse_transaction_line(
            ":61:260320RD100,00NTRF//TX2", summary
        )
        self.assertEqual(t_rd["amount"], Decimal("100.00"))

        # Expected Debit (ED) -> negative
        t_ed = Mt942Parser._parse_transaction_line(
            ":61:260320ED50,00NTRF//TX3", summary
        )
        self.assertEqual(t_ed["amount"], Decimal("-50.00"))

        # Expected Credit (EC) -> positive
        t_ec = Mt942Parser._parse_transaction_line(
            ":61:260320EC50,00NTRF//TX4", summary
        )
        self.assertEqual(t_ec["amount"], Decimal("50.00"))

        # Malformed :61: line
        with self.assertRaises(ValidationError) as ctx:
            Mt942Parser._parse_transaction_line(":61:INVALID", summary)
        self.assertIn("Malformed MT942 :61:", str(ctx.exception))

    def test_multi_account_scope_parsing(self) -> None:
        """Test handling multiple account scopes within a single MT942 file."""
        content = (
            ":20:MSG-01\n"
            ":21:REF-01\n"
            ":25:ACC-01\n"
            ":28C:1/1\n"
            ":34F:EUR10,00\n"
            ":61:260320C100,00NTRF//TX1\n"
            ":86:First account payment\n"
            ":20:MSG-02\n"
            ":25:ACC-02\n"
            ":34F:USD20,00\n"
            ":61:260320D50,00NTRF//TX2\n"
            ":86:Second account payment\n"
            "-\n"
        )
        with tempfile.NamedTemporaryFile(
            suffix=".mt942", mode="w", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            parser = Mt942Parser(tmp_path)
            df = parser.parse()
            self.assertEqual(len(df), 2)
            summaries = parser.get_summaries()
            self.assertEqual(len(summaries), 2)
            self.assertEqual(summaries[0]["account_id"], "ACC-01")
            self.assertEqual(summaries[0]["currency"], "EUR")
            self.assertEqual(summaries[1]["account_id"], "ACC-02")
            self.assertEqual(summaries[1]["currency"], "USD")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_empty_statement_dataframe(self) -> None:
        """Test empty MT942 statement produces empty DataFrame with schema."""
        content = ":20:EMPTY-01\n:25:ACC-EMPTY\n:34F:EUR0,00\n"
        with tempfile.NamedTemporaryFile(
            suffix=".mt942", mode="w", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            parser = Mt942Parser(tmp_path)
            df = parser.parse()
            self.assertTrue(df.empty)
            self.assertListEqual(
                list(df.columns),
                [
                    "date",
                    "amount",
                    "transaction_id",
                    "account_id",
                    "currency",
                    "description",
                ],
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_statement_without_scope_tags(self) -> None:
        """Test parsing statement without any scope tags."""
        content = ":99:Unrelated\n-\n"
        with tempfile.NamedTemporaryFile(
            suffix=".mt942", mode="w", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            parser = Mt942Parser(tmp_path)
            df = parser.parse()
            self.assertTrue(df.empty)
            summaries = parser.get_summaries()
            self.assertEqual(len(summaries), 1)
            self.assertIsNone(summaries[0]["account_id"])
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_edge_cases_in_grammar(self) -> None:
        """Test parser edge cases including narratives without transactions and empty tags."""
        content = (
            ":20:\n"  # empty message_id
            ":25:\n"  # empty account_id
            ":28C:\n"  # empty statement_id
            ":86:Narrative before any transaction\n"
            "continuation line\n"
            ":25:ACC-SUBSEQUENT\n"  # new scope by :25:
            ":34F:EUR50,00\n"
            ":61:260320C25,00\n"  # transaction with no id
            ":86:\n"  # empty narrative line
            ":99:Unknown tag\n"  # unhandled tag
            "-}\n"
        )
        with tempfile.NamedTemporaryFile(
            suffix=".mt942", mode="w", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            parser = Mt942Parser(tmp_path)
            df = parser.parse()
            self.assertEqual(len(df), 1)
            self.assertIsNone(df.iloc[0]["transaction_id"])
            self.assertIsNone(df.iloc[0]["description"])
            self.assertEqual(df.iloc[0]["account_id"], "ACC-SUBSEQUENT")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_append_narrative_direct(self) -> None:
        """Test _append_narrative handling of continuation lines and delimiters."""
        tx: dict = {"description": None}
        self.assertTrue(Mt942Parser._append_narrative("continuation 1", tx))
        self.assertEqual(tx["description"], "continuation 1")
        self.assertFalse(Mt942Parser._append_narrative(":61:new tag", tx))
        self.assertFalse(Mt942Parser._append_narrative("-end-of-message", tx))

    def test_get_summaries_before_parse(self) -> None:
        """Test calling get_summaries before parse triggers parsing automatically."""
        parser = Mt942Parser(self.sample_file)
        summaries = parser.get_summaries()
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["account_id"], "NL91ABNA0417164300")

    def test_backfill_currency_and_account(self) -> None:
        """Test transactions backfill currency and account when declared after :61:."""
        content = (
            ":20:MSG-BACKFILL\n"
            ":61:260320C100,00NTRF\n"
            ":25:ACC-BACKFILL\n"
            ":34F:EUR10,00\n"
        )
        with tempfile.NamedTemporaryFile(
            suffix=".mt942", mode="w", delete=False
        ) as f:
            f.write(content)
            tmp_path = f.name
        try:
            parser = Mt942Parser(tmp_path)
            rows = parser.parse_streaming()
            self.assertEqual(rows[0]["account_id"], "ACC-BACKFILL")
            self.assertEqual(rows[0]["currency"], "EUR")
        finally:
            Path(tmp_path).unlink(missing_ok=True)
