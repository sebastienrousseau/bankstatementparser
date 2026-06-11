# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Golden-file behavior tests.

Each fixture under ``tests/test_data/golden/`` pins the exact parsed
output for a realistic statement shape. These tests are the contract:
if a refactor changes any value here, that change is user-visible and
must be deliberate.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bankstatementparser import Deduplicator
from bankstatementparser.additional_parsers import CsvStatementParser
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.input_validator import ValidationError

GOLDEN = Path(__file__).parent / "test_data" / "golden"


class TestMultiCurrencyCamt:
    def test_transactions_keep_per_statement_currency(self) -> None:
        parser = CamtParser(GOLDEN / "camt053_multicurrency.xml")
        df = parser.get_transactions()

        assert len(df) == 3
        assert df["Currency"].tolist() == ["EUR", "EUR", "USD"]
        assert df["Amount"].tolist() == [
            Decimal("1250.50"),
            Decimal("-500.25"),
            Decimal("-99.99"),
        ]
        assert df["AccountId"].tolist() == [
            "DE89370400440532013000",
            "DE89370400440532013000",
            "US-ACCT-0099",
        ]

    def test_balances_per_account(self) -> None:
        parser = CamtParser(GOLDEN / "camt053_multicurrency.xml")
        balances = parser.get_account_balances()

        eur = balances[balances["AccountId"] == "DE89370400440532013000"]
        usd = balances[balances["AccountId"] == "US-ACCT-0099"]
        assert dict(zip(eur["Code"], eur["Amount"], strict=True)) == {
            "OPBD": Decimal("10000.00"),
            "CLBD": Decimal("10750.25"),
        }
        assert dict(zip(usd["Code"], usd["Amount"], strict=True)) == {
            "OPBD": Decimal("2500.00"),
            "CLBD": Decimal("2400.01"),
        }

    def test_statement_stats_net_amounts(self) -> None:
        parser = CamtParser(GOLDEN / "camt053_multicurrency.xml")
        stats = parser.get_statement_stats()

        by_id = {row["StatementId"]: row for row in stats.to_dict("records")}
        assert by_id["GOLDEN-MULTI-EUR"]["NumTransactions"] == 2
        assert by_id["GOLDEN-MULTI-EUR"]["NetAmount"] == Decimal("750.25")
        assert by_id["GOLDEN-MULTI-USD"]["NumTransactions"] == 1
        assert by_id["GOLDEN-MULTI-USD"]["NetAmount"] == Decimal("-99.99")


class TestNoNamespaceCamt:
    def test_parses_without_xmlns(self) -> None:
        parser = CamtParser(GOLDEN / "camt053_no_namespace.xml")
        df = parser.get_transactions()

        assert len(df) == 1
        row = df.iloc[0]
        assert row["Amount"] == Decimal("250.00")
        assert row["Currency"] == "GBP"
        assert row["Debtor"] == "JANE CLIENT"
        assert row["Reference"] == "Consulting fee"
        assert row["AccountId"] == "GB29NWBK60161331926819"


class TestDuplicateSameDayCamt:
    def test_parser_keeps_both_rows(self) -> None:
        parser = CamtParser(GOLDEN / "camt053_duplicate_same_day.xml")
        df = parser.get_transactions()

        assert len(df) == 2
        assert df["Amount"].tolist() == [
            Decimal("-4.50"),
            Decimal("-4.50"),
        ]

    def test_dedupe_keeps_genuine_repeats_but_is_idempotent(
        self,
    ) -> None:
        parser = CamtParser(GOLDEN / "camt053_duplicate_same_day.xml")
        dedup = Deduplicator()
        txs = dedup.from_dataframe(parser.get_transactions(), source="golden")

        seen: set[str] = set()
        unique, skipped = dedup.dedupe_by_hash(txs, seen_hashes=seen)
        assert len(unique) == 2
        assert skipped == []

        unique2, skipped2 = dedup.dedupe_by_hash(txs, seen_hashes=seen)
        assert unique2 == []
        assert len(skipped2) == 2


class TestGarbledAmounts:
    def test_camt_garbled_amount_raises(self) -> None:
        parser = CamtParser(GOLDEN / "camt053_garbled_amount.xml")
        with pytest.raises(ValueError, match=r"12\.\.34"):
            parser.get_transactions()

    def test_csv_garbled_amount_raises(self) -> None:
        parser = CsvStatementParser(GOLDEN / "csv_garbled_amount.csv")
        with pytest.raises(ValidationError, match=r"12\.\.34"):
            parser.parse()


class TestEuropeanDecimalCsv:
    def test_german_headers_and_comma_decimals(self) -> None:
        parser = CsvStatementParser(GOLDEN / "csv_european_decimals.csv")
        df = parser.parse()

        assert df["date"].tolist() == [
            "2026-04-02",
            "2026-04-05",
            "2026-04-09",
        ]
        assert df["description"].tolist() == [
            "Miete April",
            "Gehalt",
            "Kaffee",
        ]
        assert df["amount"].tolist() == [
            Decimal("-1234.56"),
            Decimal("3500.00"),
            Decimal("-4.50"),
        ]

        summary = parser.get_summary()
        assert summary["transaction_count"] == 3
        assert summary["total_amount"] == Decimal("2260.94")
        assert summary["currency"] == "EUR"
