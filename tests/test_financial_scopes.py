# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Regressions for financial totals that must retain their account and currency."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from bankstatementparser.additional_parsers import (
    CsvStatementParser,
    OfxParser,
)
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.exceptions import Pain001ParseError, ParserError
from bankstatementparser.pain001_parser import Pain001Parser


def test_csv_summary_scopes_missing_metadata_and_precision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "scopes.csv"
    path.write_text(
        "date,amount,account,currency,balance\n"
        "2026-01-01,1.234,0001,KWD,5.234\n"
        "2026-01-02,-0.001,0001,KWD,5.233\n"
        "2026-01-01,10,0001,EUR,100\n"
        "2026-01-01,20,0002,EUR,200\n"
        ",3,,,\n"
    )
    parser = CsvStatementParser(path)
    summaries = parser.get_summaries()
    assert len(summaries) == 4
    assert summaries[0]["total_amount"] == Decimal("1.233")
    assert summaries[0]["account_id"] == "0001"
    assert summaries[0]["closing_balance"] == Decimal("5.233")
    assert summaries[0]["opening_balance"] is None
    assert summaries[-1]["currency"] is None
    assert summaries[-1]["statement_date"] is None
    with pytest.raises(ValueError, match="get_summaries"):
        parser.get_summary()
    output = tmp_path / "scopes.json"
    parser.export_json(output)
    data = json.loads(output.read_text())
    assert data["summary"] is None
    assert len(data["summaries"]) == 4
    assert data["summaries"][0]["total_amount"] == "1.233"


def test_ofx_scoped_summary_matches_account_metadata(tmp_path: Path) -> None:
    path = tmp_path / "scopes.ofx"
    path.write_text(
        "<OFX>"
        + "".join(
            f"<STMTRS><CURDEF>{currency}</CURDEF><BANKACCTFROM><ACCTID>{account}</ACCTID>"
            f"</BANKACCTFROM><BANKTRANLIST><STMTTRN><DTPOSTED>20260101</DTPOSTED>"
            f"<TRNAMT>{amount}</TRNAMT><FITID>{account}</FITID></STMTTRN></BANKTRANLIST></STMTRS>"
            for account, currency, amount in (
                ("A", "EUR", "10"),
                ("B", "USD", "20"),
            )
        )
        + "</OFX>"
    )
    parser = OfxParser(path)
    assert [
        (s["account_id"], s["currency"], s["total_amount"])
        for s in parser.get_summaries()
    ] == [("A", "EUR", Decimal("10")), ("B", "USD", Decimal("20"))]
    with pytest.raises(ValueError, match="get_summaries"):
        parser.get_summary()


def _balance(currency: str, amount: str, code: str) -> str:
    return (
        f'<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp><Amt Ccy="{currency}">{amount}</Amt>'
        "<CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2026-01-01</Dt></Dt></Bal>"
    )


def test_camt_summaries_keep_statement_currency_and_balances(
    tmp_path: Path,
) -> None:
    path = tmp_path / "scopes.xml"
    path.write_text(
        "<Document><BkToCstmrStmt>"
        "<Stmt><Id>first</Id><Acct><Id><IBAN>A</IBAN></Id><Ccy>EUR</Ccy></Acct>"
        '<Ntry><Amt Ccy="EUR">10</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry>'
        '<Ntry><Amt Ccy="KWD">1.234</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry>'
        + _balance("EUR", "100", "OPBD")
        + _balance("KWD", "2.345", "CLBD")
        + "</Stmt><Stmt><Id>second</Id><Acct><Id><IBAN>B</IBAN></Id></Acct>"
        + _balance("EUR", "999", "CLBD")
        + "</Stmt></BkToCstmrStmt></Document>"
    )
    parser = CamtParser(str(path))
    rows = parser.get_summaries()
    assert [
        (r["statement_id"], r["account_id"], r["currency"]) for r in rows
    ] == [("first", "A", "EUR"), ("first", "A", "KWD"), ("second", "B", "EUR")]
    assert rows[0]["opening_balance"] == Decimal("100")
    assert "closing_balance" not in rows[0]
    assert rows[1]["total_amount"] == Decimal("-1.234")
    assert rows[1]["closing_balance"] == Decimal("2.345")
    assert rows[2]["transaction_count"] == 0
    assert rows[2]["closing_balance"] == Decimal("999")
    assert all(
        r["account_id"] == "***REDACTED***" for r in parser.get_summaries(True)
    )
    with pytest.raises(ValueError, match="get_summaries"):
        parser.get_summary()
    stats = parser.get_statement_stats().to_dict("records")
    assert stats[0]["NetAmount"] is None
    assert stats[0]["NetAmountByCurrency"] == {
        "EUR": Decimal("10"),
        "KWD": Decimal("-1.234"),
    }


@pytest.mark.parametrize(
    "entry",
    [
        "<Ntry/>",
        '<Ntry><Amt Ccy="EUR">1</Amt><CdtDbtInd>UNKNOWN</CdtDbtInd></Ntry>',
    ],
)
def test_camt_summary_rejects_incomplete_booked_entries(
    tmp_path: Path, entry: str
) -> None:
    path = tmp_path / "bad.xml"
    path.write_text(f"<Document><Stmt>{entry}</Stmt></Document>")
    with pytest.raises(ParserError, match="booked amount"):
        CamtParser(str(path)).get_summary()


def test_camt_summary_rejects_ambiguous_balances(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.xml"
    path.write_text(
        "<Document><Stmt>"
        + _balance("EUR", "1", "OPBD") * 2
        + "</Stmt></Document>"
    )
    with pytest.raises(ParserError, match="Ambiguous duplicate"):
        CamtParser(str(path)).get_summary()


def test_pain_summary_counts_rows_by_account_and_currency(
    tmp_path: Path,
) -> None:
    path = tmp_path / "payments.xml"
    path.write_text(
        "<Document><CstmrCdtTrfInitn><GrpHdr><NbOfTxs>999</NbOfTxs></GrpHdr>"
        + "".join(
            f"<PmtInf><DbtrAcct><Id><IBAN>{account}</IBAN></Id></DbtrAcct><CdtTrfTxInf>"
            f'<Amt><InstdAmt Ccy="{currency}">{amount}</InstdAmt></Amt></CdtTrfTxInf></PmtInf>'
            for account, currency, amount in (
                ("A", "EUR", "10"),
                ("A", "EUR", "20"),
                ("A", "KWD", "1.234"),
                ("B", "EUR", "3"),
            )
        )
        + "</CstmrCdtTrfInitn></Document>"
    )
    parser = Pain001Parser(str(path))
    rows = parser.get_summaries()
    assert [r["transaction_count"] for r in rows] == [2, 1, 1]
    assert [r["total_amount"] for r in rows] == [
        Decimal("30"),
        Decimal("1.234"),
        Decimal("3"),
    ]
    assert all(
        r["account_id"] == "***REDACTED***" for r in parser.get_summaries(True)
    )
    with pytest.raises(ValueError, match="get_summaries"):
        parser.get_summary()
    path.write_text(
        "<Document><CstmrCdtTrfInitn><GrpHdr><NbOfTxs>999</NbOfTxs></GrpHdr></CstmrCdtTrfInitn></Document>"
    )
    assert Pain001Parser(str(path)).get_summary()["transaction_count"] == 0


def test_pain_summary_rejects_missing_amount(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.xml"
    path.write_text(
        "<Document><CstmrCdtTrfInitn><PmtInf><CdtTrfTxInf/></PmtInf></CstmrCdtTrfInitn></Document>"
    )
    with pytest.raises(Pain001ParseError, match="every payment amount"):
        Pain001Parser(str(path)).get_summaries()


def test_camt_foreign_amounts_and_payment_identifiers(tmp_path: Path) -> None:
    from bankstatementparser.reconciliation import (
        reconcile_payments_and_statements,
    )
    from bankstatementparser.transaction_models import Transaction

    path = tmp_path / "fx.xml"
    path.write_text("""<Document><Stmt><Acct><Id><IBAN>ACCOUNT</IBAN></Id></Acct>
      <Ntry><Amt Ccy="EUR">120</Amt><CdtDbtInd>DBIT</CdtDbtInd>
      <NtryDtls><TxDtls><Refs><EndToEndId>payment-1</EndToEndId><AcctSvcrRef>bank-1</AcctSvcrRef></Refs>
      <AmtDtls><TxAmt><Amt Ccy="JPY">20000</Amt></TxAmt>
      <InstdAmt><Amt Ccy="USD">130</Amt></InstdAmt></AmtDtls>
      <RmtInf><Ustrd>Invoice narrative</Ustrd><Strd><CdtrRefInf><Ref>RF123</Ref></CdtrRefInf></Strd></RmtInf>
      </TxDtls></NtryDtls></Ntry></Stmt></Document>""")
    parser = CamtParser(str(path))
    row = parser.parse().to_dict("records")[0]
    assert row == next(parser.parse_streaming())
    assert (row["Amount"], row["Currency"]) == (Decimal("-120"), "EUR")
    assert row["TransactionAmount"] == Decimal("20000")
    assert row["TransactionCurrency"] == "JPY"
    assert row["InstructedAmount"] == Decimal("130")
    assert row["InstructedCurrency"] == "USD"
    assert row["Reference"] == "Invoice narrative RF123"
    normalized = Transaction.from_record(row)
    assert normalized.transaction_id == "bank-1"
    assert normalized.end_to_end_id == "payment-1"
    payment = {
        "InstdAmt": "120",
        "Currency": "EUR",
        "EndToEndId": "payment-1",
        "DbtrIBAN": "ACCOUNT",
    }
    for statement in (row, normalized):
        assert (
            reconcile_payments_and_statements(
                [payment], [statement]
            ).matched_count
            == 1
        )
    masked = next(parser.parse_streaming(True))
    assert masked["EndToEndId"] == masked["AcctSvcrRef"] == "***REDACTED***"


def test_camt_batch_uses_countervalue_without_borrowing_sibling_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "batch.xml"
    path.write_text("""<Document><Stmt><Ntry><Amt Ccy="EUR">30</Amt><CdtDbtInd>DBIT</CdtDbtInd>
      <NtryDtls><TxDtls><AmtDtls><TxAmt><Amt Ccy="USD">11</Amt></TxAmt>
      <CntrValAmt><Amt Ccy="EUR">10</Amt></CntrValAmt></AmtDtls>
      <Refs><EndToEndId>first</EndToEndId></Refs><RltdPties><Cdtr><Nm>First vendor</Nm></Cdtr></RltdPties>
      <RmtInf><Ustrd>First invoice</Ustrd></RmtInf></TxDtls>
      <TxDtls><Amt Ccy="EUR">20</Amt></TxDtls></NtryDtls></Ntry></Stmt></Document>""")
    parser = CamtParser(str(path))
    first, second = list(parser.parse_streaming())
    assert first["Amount"] == Decimal("-10")
    assert first["CounterValueAmount"] == Decimal("10")
    assert first["CounterValueCurrency"] == "EUR"
    assert second["Amount"] == Decimal("-20")
    assert second["Creditor"] == second["Reference"] == ""
    assert "EndToEndId" not in second


@pytest.mark.parametrize(
    "detail, message",
    [
        ('<Amt Ccy="USD">1</Amt>', "missing booked amount"),
        (
            '<Amt Ccy="EUR">1</Amt><AmtDtls><TxAmt><Amt Ccy="EUR">2</Amt></TxAmt></AmtDtls>',
            "Ambiguous booked",
        ),
        (
            '<Amt Ccy="EUR">1</Amt><CdtDbtInd>UNKNOWN</CdtDbtInd>',
            "Invalid transaction detail",
        ),
    ],
)
def test_camt_batch_rejects_unprovable_booked_amounts(
    tmp_path: Path, detail: str, message: str
) -> None:
    path = tmp_path / "bad-batch.xml"
    path.write_text(
        f'<Document><Stmt><Ntry><Amt Ccy="EUR">2</Amt><CdtDbtInd>DBIT</CdtDbtInd><NtryDtls><TxDtls>{detail}</TxDtls><TxDtls><Amt Ccy="EUR">1</Amt></TxDtls></NtryDtls></Ntry></Stmt></Document>'
    )
    with pytest.raises(ParserError, match=message):
        CamtParser(str(path)).parse()


@pytest.mark.parametrize(
    "direction, detail, message",
    [
        ("UNKNOWN", "", "Invalid booked"),
        (
            "DBIT",
            "<NtryDtls><TxDtls><CdtDbtInd>CRDT</CdtDbtInd></TxDtls></NtryDtls>",
            "direction conflicts",
        ),
    ],
)
def test_camt_rejects_contradictory_direction(
    tmp_path: Path, direction: str, detail: str, message: str
) -> None:
    path = tmp_path / "direction.xml"
    path.write_text(
        f'<Document><Stmt><Ntry><Amt Ccy="EUR">1</Amt><CdtDbtInd>{direction}</CdtDbtInd>{detail}</Ntry></Stmt></Document>'
    )
    with pytest.raises(ParserError, match=message):
        CamtParser(str(path)).parse()


def test_mt940_statement_boundaries_signed_balances_and_funds_code(
    tmp_path: Path,
) -> None:
    from bankstatementparser.additional_parsers import Mt940Parser

    path = tmp_path / "periods.mt940"
    path.write_text(
        ":20:FIRST\n:25:A\n:28C:001/1\n:60F:D260101EUR100,00\n"
        ":61:260102DR10,00NTRFNONREF//BANK1\n:86:Purchase\n"
        ":62F:D260102EUR110,00\n:86:Statement narrative\n"
        ":20:SECOND\n:25:A\n:28C:002/1\n:60F:D260103EUR110,00\n"
        ":61:260103RD10,00NTRFNONREF//BANK2\n:62F:D260103EUR100,00\n"
    )
    parser = Mt940Parser(path)
    rows = parser.parse().to_dict("records")
    assert [r["amount"] for r in rows] == [Decimal("-10"), Decimal("10")]
    assert rows[0]["description"] == "Purchase"
    summaries = parser.get_summaries()
    assert [s["statement_id"] for s in summaries] == ["001/1", "002/1"]
    assert [s["opening_balance"] for s in summaries] == [
        Decimal("-100"),
        Decimal("-110"),
    ]
    assert [s["closing_balance"] for s in summaries] == [
        Decimal("-110"),
        Decimal("-100"),
    ]
    summaries[0]["account_id"] = "MUTATED"
    assert parser.get_summaries()[0]["account_id"] == "A"
    with pytest.raises(ValueError, match="get_summaries"):
        parser.get_summary()


@pytest.mark.parametrize(
    "line,reason",
    [
        (":61:INVALID", "Malformed MT940 :61:"),
        (":62F:C260101USD10,00", "Conflicting MT940 statement currencies"),
        (":60M:C260101EUR20,00", "Conflicting MT940 statement balances"),
    ],
)
def test_mt940_rejects_inconsistent_financial_lines(
    tmp_path: Path, line: str, reason: str
) -> None:
    from bankstatementparser.additional_parsers import Mt940Parser
    from bankstatementparser.input_validator import ValidationError

    path = tmp_path / "invalid.mt940"
    path.write_text(":20:REF\n:25:A\n:60F:C260101EUR10,00\n" + line)
    with pytest.raises(ValidationError, match=reason):
        Mt940Parser(path).parse()


def test_mt940_empty_scope_and_metadata_reset(tmp_path: Path) -> None:
    from bankstatementparser.additional_parsers import Mt940Parser

    path = tmp_path / "empty.mt940"
    path.write_text(
        ":20:REF\n:25:A\n:60F:C260101EUR10,00\n:20:NEXT\n:25:B\n:61:260101C1,00\n"
    )
    parser = Mt940Parser(path)
    assert parser.parse().iloc[0]["currency"] is None
    summaries = parser.get_summaries()
    assert summaries[0]["transaction_count"] == 0
    assert summaries[1]["currency"] is None


def test_camt_wrapper_balances_stay_with_statement_and_currency(
    tmp_path: Path,
) -> None:
    from bankstatementparser.bank_statement_parsers import (
        Camt053Parser,
        FileParserError,
    )

    path = tmp_path / "same-account.xml"
    path.write_text(
        "<Document>"
        + "".join(
            "<Stmt><Acct><Id><IBAN>A</IBAN></Id></Acct>" + balances + "</Stmt>"
            for balances in (
                _balance("EUR", "10", "OPBD"),
                _balance("EUR", "20", "OPBD") + _balance("USD", "30", "OPBD"),
            )
        )
        + "</Document>"
    )
    with pytest.warns(DeprecationWarning):
        wrapper = Camt053Parser(path, redact_pii=True)
    assert wrapper.statements[0]["OPBD"]["Amount"] == "10"
    assert "OPBD" not in wrapper.statements[1]
    assert (
        wrapper.statements[1]["BalancesByCurrency"]["EUR"]["OPBD"]["Amount"]
        == "20"
    )
    assert (
        wrapper.statements[1]["BalancesByCurrency"]["USD"]["OPBD"]["Amount"]
        == "30"
    )
    path.write_text(
        "<Document><Stmt><Acct><Id><IBAN>A</IBAN></Id></Acct>"
        + _balance("EUR", "1", "CLAV") * 2
        + "</Stmt></Document>"
    )
    with pytest.warns(DeprecationWarning), pytest.raises(FileParserError):
        Camt053Parser(path)


@pytest.mark.parametrize(
    "identity", [None, "", "NONREF", "NOTPROVIDED", "UNKNOWN", "N/A"]
)
def test_identical_purchases_without_identity_keep_every_occurrence(
    identity: str | None,
) -> None:
    from bankstatementparser import Deduplicator

    row = {
        "amount": "10",
        "date": "2026-01-01",
        "currency": "EUR",
        "account_id": "A",
        "description": "Coffee",
        "transaction_id": identity,
    }
    result = Deduplicator().deduplicate([row, row])
    assert len(result.unique_transactions) == 2
    assert result.exact_duplicates == []
    assert result.suspected_matches == []


def test_probable_pair_does_not_capture_unrelated_bucket_members() -> None:
    from bankstatementparser import Deduplicator

    base = {
        "amount": "10",
        "date": "2026-01-01",
        "currency": "EUR",
        "account_id": "A",
    }
    result = Deduplicator().deduplicate(
        [
            {
                **base,
                "description": "Coffee shop London",
                "transaction_id": "ONE",
            },
            {
                **base,
                "description": "Coffee shop Londn",
                "transaction_id": "ONE",
            },
            {
                **base,
                "description": "Coffee shop Londn",
                "transaction_id": "TWO",
            },
            {**base, "description": "Train fare"},
        ]
    )
    assert len(result.suspected_matches) == 1
    assert len(result.suspected_matches[0].transactions) == 2
    assert [r.transaction_id for r in result.unique_transactions] == [
        "TWO",
        None,
    ]
