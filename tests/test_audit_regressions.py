# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Financial correctness regressions found during the September 2026 audit."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bankstatementparser.additional_parsers import (
    CsvStatementParser,
    Mt940Parser,
    OfxParser,
)
from bankstatementparser.analytics import compute_cash_flow_summary
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.exceptions import ParserError
from bankstatementparser.input_validator import ValidationError
from bankstatementparser.privacy import redact_record
from bankstatementparser.reconciliation import (
    reconcile_payments_and_statements,
)
from bankstatementparser.transaction_models import Transaction


def test_csv_preserves_decimal_and_identifier(tmp_path: Path) -> None:
    path = tmp_path / "precision.csv"
    path.write_text(
        "date,amount,account,currency\n2026-09-25,9007199254740993.01,000123,USD\n"
    )
    row = CsvStatementParser(path).parse().iloc[0]
    assert row["amount"] == Decimal("9007199254740993.01")
    assert row["account_id"] == "000123"
    path.write_text("date,description\n2026-09-25,Unknown amount\n")
    with pytest.raises(ValidationError, match="requires an amount"):
        CsvStatementParser(path).parse()


def test_mt940_date_normalizes_before_transaction_model(
    tmp_path: Path,
) -> None:
    path = tmp_path / "date.mt940"
    path.write_text(
        ":20:STATEMENT\n:25:000123\n:60F:C260925EUR0,00\n:61:260925D10,00NONREF\n:86:Purchase\n"
    )
    record = Mt940Parser(path).parse().iloc[0].to_dict()
    assert Transaction.from_record(record).booking_date == date(2026, 9, 25)


def test_ofx_keeps_each_statement_account_and_currency(tmp_path: Path) -> None:
    path = tmp_path / "accounts.ofx"
    path.write_text(
        "<OFX>"
        + "".join(
            f"<{tag}><CURDEF>{currency}<ACCTID>{account}<BANKTRANLIST><STMTTRN><DTPOSTED>20260925<TRNAMT>12.30<FITID>{account}</STMTTRN></BANKTRANLIST></{tag}>"
            for tag, currency, account in [
                ("STMTRS", "USD", "0001"),
                ("CCSTMTRS", "GBP", "0002"),
            ]
        )
        + "</OFX>"
    )
    records = OfxParser(path).parse().to_dict("records")
    assert [(r["currency"], r["account_id"]) for r in records] == [
        ("USD", "0001"),
        ("GBP", "0002"),
    ]


@pytest.mark.parametrize("prefix", ["", "c:"])
@pytest.mark.parametrize("quote", ['"', "'"])
def test_camt_namespace_and_batch_stream_parity(
    prefix: str, quote: str
) -> None:
    from lxml import etree

    xml = '<Document><BkToCstmrStmt><Stmt><Acct><Id><IBAN>000123</IBAN></Id></Acct><Ntry><Amt Ccy="EUR">30.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><NtryDtls>'
    xml += "".join(
        f'<TxDtls><AmtDtls><TxAmt><Amt Ccy="EUR">{amount}</Amt></TxAmt></AmtDtls><RmtInf><Ustrd>{name}</Ustrd></RmtInf></TxDtls>'
        for amount, name in [("10.00", "One"), ("20.00", "Two")]
    )
    xml += "</NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>"
    root = etree.fromstring(xml)
    namespace = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
    for elem in root.iter():
        elem.tag = f"{{{namespace}}}{elem.tag}"
    etree.cleanup_namespaces(
        root, top_nsmap={"c" if prefix else None: namespace}
    )
    data = etree.tostring(root).decode().replace('"', quote)
    parser = CamtParser.from_string(data)
    records = parser.parse().to_dict("records")
    assert records == list(parser.parse_streaming())
    assert [r["Amount"] for r in records] == [
        Decimal("-10.00"),
        Decimal("-20.00"),
    ]
    assert sum(r["Amount"] for r in records) == Decimal("-30.00")
    redacted = list(parser.parse_streaming(redact_pii=True))
    assert (
        redacted[0]["Reference"]
        == redacted[0]["AccountId"]
        == "***REDACTED***"
    )


def test_camt_ambiguous_batch_fails() -> None:
    parser = CamtParser.from_string(
        '<Document><Stmt><Ntry><Amt Ccy="EUR">30</Amt><CdtDbtInd>DBIT</CdtDbtInd><NtryDtls><TxDtls/><TxDtls/></NtryDtls></Ntry></Stmt></Document>'
    )
    for parse in (parser.parse, lambda: list(parser.parse_streaming())):
        with pytest.raises(ParserError, match="missing booked amount"):
            parse()


def test_hash_scopes_account_currency_and_identity() -> None:
    tx = Transaction(
        account_id="A",
        currency="EUR",
        amount=Decimal("10.00"),
        booking_date=date(2026, 9, 25),
        description="Purchase",
        transaction_id="one",
    )
    assert tx.transaction_hash.startswith("v2:")
    for update in [
        {"account_id": "B"},
        {"currency": "USD"},
        {"transaction_id": "two"},
        {"description": "Different purchase"},
    ]:
        assert (
            tx.transaction_hash
            != tx.model_copy(update=update).transaction_hash
        )


def test_analytics_accepts_camt_and_preserves_minor_units() -> None:
    metrics = compute_cash_flow_summary(
        [
            {
                "Amount": Decimal("1.234"),
                "Currency": "KWD",
                "BookgDt": "2026-09-25",
            }
        ]
    )
    assert metrics["KWD"].net_cash_flow == Decimal("1.234")
    with pytest.raises(ValueError):
        compute_cash_flow_summary([{"Amount": "garbage", "Currency": "USD"}])


def test_reconciliation_rejects_conflicting_evidence_and_ambiguity() -> None:
    payment = {
        "InstdAmt": "100",
        "Currency": "EUR",
        "EndToEndId": "REF-123",
        "CdtrNm": "Vendor",
        "DbtrIBAN": "A",
        "ReqdExctnDt": "2026-09-25",
    }
    statement = {
        "Amount": "-100",
        "Currency": "EUR",
        "Reference": "REF-123",
        "Creditor": "Vendor",
        "AccountId": "A",
        "BookgDt": "2026-09-25",
    }
    assert (
        reconcile_payments_and_statements([payment], [statement]).matched_count
        == 1
    )
    for change in [
        {"Currency": "USD"},
        {"Amount": "100"},
        {"Reference": "REF-1234"},
        {"Amount": "-1"},
        {"AccountId": "B"},
        {"BookgDt": "2026-08-25"},
    ]:
        assert (
            reconcile_payments_and_statements(
                [payment], [statement | change]
            ).matched_count
            == 0
        )
    assert (
        reconcile_payments_and_statements(
            [payment], [statement, statement]
        ).matched_count
        == 0
    )
    assert (
        reconcile_payments_and_statements(
            [payment, payment], [statement]
        ).matched_count
        == 0
    )
    assert (
        reconcile_payments_and_statements(
            [{"InstdAmt": "100", "Currency": "EUR", "CdtrNm": "Vendor"}],
            [{"Amount": "-100", "Currency": "EUR"}],
        ).matched_count
        == 0
    )


def test_redaction_removes_names_narratives_and_provenance() -> None:
    row = {
        "Debtor": "Alice",
        "Creditor": "Bob",
        "Reference": "Personal message",
        "raw_source_text": "IBAN: private",
        "Amount": Decimal("1.234"),
        "BookgDt": "2026-09-25",
    }
    redacted = redact_record(row)
    assert all(
        redacted[k] == "***REDACTED***"
        for k in ["Debtor", "Creditor", "Reference", "raw_source_text"]
    )
    assert redacted["Amount"] == row["Amount"]
    assert row["Debtor"] == "Alice"


@pytest.mark.parametrize("root_path", ["", "/gateway"])
def test_real_api_openapi_ingestion_and_upload_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root_path: str
) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("python_multipart")
    pytest.importorskip("httpx")
    import tempfile

    from fastapi.testclient import TestClient

    from bankstatementparser import __version__
    from bankstatementparser.api import create_app

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with TestClient(
        create_app(max_upload_bytes=100), root_path=root_path
    ) as client:
        assert client.get(f"{root_path}/openapi.json").status_code == 200
        assert (
            client.get(f"{root_path}/health").json()["version"] == __version__
        )
        response = client.post(
            f"{root_path}/ingest",
            files={
                "file": (
                    "data.csv",
                    b"date,amount,currency\n2026-09-25,12.30,EUR\n",
                    "text/csv",
                )
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["transaction_count"] == 1
        assert (
            client.post(
                f"{root_path}/ingest",
                files={"file": ("large.csv", b"x" * 101)},
            ).status_code
            == 413
        )
        # Reject raw oversized multipart bodies before the decoder starts,
        # whether the transport supplies a length or streams chunks.
        from unittest.mock import AsyncMock

        from starlette.formparsers import MultiPartParser

        parse = AsyncMock(side_effect=AssertionError("multipart decoder ran"))
        monkeypatch.setattr(MultiPartParser, "parse", parse)
        for content in (b"x" * 66000, iter([b"x" * 33000] * 2)):
            assert (
                client.post(
                    f"{root_path}/ingest",
                    content=content,
                    headers={
                        "content-type": "multipart/form-data; boundary=test"
                    },
                ).status_code
                == 413
            )
        parse.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_parquet_roundtrip_preserves_decimal_and_date() -> None:
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    from bankstatementparser.export.parquet import export_parquet

    table = pq.read_table(
        pa.BufferReader(
            export_parquet(
                [{"amount": Decimal("1.234"), "date": date(2026, 9, 25)}]
            )
        )
    )
    assert pa.types.is_decimal(table.schema.field("amount").type)
    assert pa.types.is_date(table.schema.field("date").type)
    assert table.to_pylist() == [
        {"amount": Decimal("1.234"), "date": date(2026, 9, 25)}
    ]


@pytest.mark.parametrize("value", [None, float("nan"), ""])
def test_blank_split_csv_amount_is_zero(value: object) -> None:
    from bankstatementparser.additional_parsers import _amount_or_zero

    assert _amount_or_zero(value, context="blank debit cell") == Decimal("0")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_transaction_amount_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        Transaction.from_record({"amount": value})


@pytest.mark.parametrize(
    "settings",
    [
        {"fuzzy_threshold": -1},
        {"fuzzy_threshold": 2},
        {"fee_tolerance": Decimal("-1")},
        {"fee_tolerance": Decimal("NaN")},
        {"max_date_gap_days": -1},
    ],
)
def test_reconciliation_invalid_configuration(settings: dict) -> None:
    with pytest.raises(ValueError):
        reconcile_payments_and_statements([], [], **settings)


def test_reconciliation_direction_placeholders_and_low_similarity() -> None:
    payment = {
        "InstdAmt": "10",
        "Currency": "EUR",
        "EndToEndId": "NOTPROVIDED",
        "CdtrNm": "Alpha",
    }
    statement = {
        "Amount": "10",
        "Currency": "EUR",
        "DrCr": "DBIT",
        "Reference": "NONREF",
        "Creditor": "Zebra",
    }
    assert (
        reconcile_payments_and_statements([payment], [statement]).matched_count
        == 0
    )
    statement["Creditor"] = "Alpha"
    assert (
        reconcile_payments_and_statements([payment], [statement]).matched_count
        == 1
    )
    statement["DrCr"] = "CRDT"
    assert (
        reconcile_payments_and_statements([payment], [statement]).matched_count
        == 0
    )


def test_camt_missing_direction_rejected() -> None:
    parser = CamtParser.from_string(
        '<Document><Stmt><Ntry><Amt Ccy="EUR">1</Amt></Ntry></Stmt></Document>'
    )
    with pytest.raises(ParserError, match="CdtDbtInd"):
        parser.parse()


@pytest.mark.parametrize("address_tag", ["AdrLine", "StrtNm", None])
@pytest.mark.parametrize("redact", [True, False])
def test_legacy_entry_reader_party_addresses(
    address_tag: str | None, redact: bool
) -> None:
    from lxml import etree

    address = (
        f"<PstlAdr><{address_tag}>Private street</{address_tag}></PstlAdr>"
        if address_tag
        else ""
    )
    entry = etree.fromstring(
        f'<Ntry><Amt Ccy="USD">1.23</Amt><CdtDbtInd>CRDT</CdtDbtInd><NtryDtls><TxDtls><RltdPties><Dbtr><Nm>Alice</Nm>{address}</Dbtr><Cdtr><Nm>Bob</Nm>{address}</Cdtr></RltdPties><RmtInf><Ustrd>Reference</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>'
    )
    parser = CamtParser.from_string("<Document/>")
    row = parser._parse_streaming_transaction(entry, "account", redact)
    assert row["Amount"] == Decimal("1.23")
    assert row["Reference"] == "Reference"
    if address_tag:
        assert row["DebtorAddress"] == (
            "***REDACTED***" if redact else "Private street"
        )
    # Optional party tags and empty references must not drop a row.
    empty = etree.fromstring(
        '<Ntry><Amt Ccy="USD">1.23</Amt><NtryDtls><TxDtls/></NtryDtls></Ntry>'
    )
    assert parser._parse_streaming_transaction(empty, "")["Amount"] == Decimal(
        "1.23"
    )


def test_forensics_never_authenticates_uninspected_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import SimpleNamespace

    from bankstatementparser.forensics import (
        ForensicVerdict,
        inspect_pdf_forensics,
    )

    monkeypatch.setitem(sys.modules, "pypdf", None)
    assert (
        inspect_pdf_forensics(b"%PDF-1.4 unavailable parser").verdict
        == ForensicVerdict.INDETERMINATE
    )
    assert inspect_pdf_forensics(b"garbage").verdict == ForensicVerdict.INVALID
    monkeypatch.setitem(
        sys.modules,
        "pypdf",
        SimpleNamespace(
            PdfReader=lambda stream: SimpleNamespace(pages=[], metadata=None)
        ),
    )
    assert (
        inspect_pdf_forensics(b"%PDF-1.4 empty").verdict
        == ForensicVerdict.INVALID
    )

    def broken_reader(stream: object) -> None:
        raise ValueError("invalid document")

    monkeypatch.setitem(
        sys.modules, "pypdf", SimpleNamespace(PdfReader=broken_reader)
    )
    assert (
        inspect_pdf_forensics(b"%PDF-1.4 invalid").verdict
        == ForensicVerdict.INVALID
    )
    monkeypatch.setitem(
        sys.modules,
        "pypdf",
        SimpleNamespace(
            PdfReader=lambda stream: SimpleNamespace(
                pages=[object()], metadata=None
            )
        ),
    )
    assert (
        inspect_pdf_forensics(b"%PDF-1.4 inspected").verdict
        == ForensicVerdict.NO_INDICATORS
    )


def test_temporal_matching_explicit_zero_similarity_threshold() -> None:
    from bankstatementparser.transaction_deduplicator import Deduplicator

    rows = [
        {
            "amount": "1",
            "currency": "EUR",
            "booking_date": "2026-09-25",
            "value_date": "2026-09-25",
        },
        {
            "amount": "1",
            "currency": "EUR",
            "booking_date": "2026-09-26",
            "value_date": "2026-09-26",
        },
    ]
    report = Deduplicator(description_similarity_threshold=0).deduplicate(rows)
    assert len(report.suspected_matches) == 1


@pytest.mark.parametrize(
    "currency,total,direction",
    [("EUR", "31", "DBIT"), ("USD", "30", "DBIT"), ("EUR", "31", "CRDT")],
)
def test_camt_batch_must_conserve_booked_amount(
    currency: str, total: str, direction: str
) -> None:
    parser = CamtParser.from_string(
        f'<Document><Stmt><Ntry><Amt Ccy="EUR">{total}</Amt><CdtDbtInd>{direction}</CdtDbtInd><NtryDtls><TxDtls><Amt Ccy="{currency}">10</Amt></TxDtls><TxDtls><Amt Ccy="EUR">20</Amt></TxDtls></NtryDtls></Ntry></Stmt></Document>'
    )
    with pytest.raises(ParserError, match="conserve"):
        parser.parse()


def test_camt_foreign_extension_entries_are_not_bank_transactions() -> None:
    parser = CamtParser.from_string(
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08" xmlns:ext="urn:vendor:extension"><Stmt><Ntry><Amt Ccy="EUR">1</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry><ext:Ntry><Amt Ccy="EUR">999</Amt><CdtDbtInd>CRDT</CdtDbtInd></ext:Ntry></Stmt></Document>'
    )
    rows = list(parser.parse_streaming())
    assert rows == parser.parse().to_dict("records")
    assert len(rows) == 1
    assert rows[0]["Amount"] == Decimal("1")
