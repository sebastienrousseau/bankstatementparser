# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Export schema, batching, atomicity and privacy regressions."""

import csv
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bankstatementparser import (
    CamtParser,
    CsvStatementParser,
    export_parquet_stream,
)
from bankstatementparser.cli import BankStatementCLI
from bankstatementparser.privacy import redact_record


def test_redaction_includes_nested_provenance_without_mutation() -> None:
    original = {
        "metadata": {
            "source": "/private/person.csv",
            "attachments": [
                {"filename": "Alice.pdf", "amount": Decimal("1.234")},
                5,
            ],
        },
        "source_method": "deterministic",
        "source": None,
        "transaction_hash": "v2:private",
    }
    masked = redact_record(original)
    assert masked["metadata"]["source"] == "***REDACTED***"
    assert masked["metadata"]["attachments"][0]["filename"] == "***REDACTED***"
    assert masked["metadata"]["attachments"][0]["amount"] == Decimal("1.234")
    assert masked["metadata"]["attachments"][1] == 5
    assert masked["source_method"] == "deterministic"
    assert masked["source"] is None
    assert masked["transaction_hash"] == "***REDACTED***"
    assert original["metadata"]["source"] == "/private/person.csv"


def test_csv_and_json_export_share_redaction_policy(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text(
        "date,amount,currency,account,description\n2026-01-01,1.234,KWD,0001,Alice\n"
    )
    parser = CsvStatementParser(source)
    csv_path, json_path = tmp_path / "masked.csv", tmp_path / "masked.json"
    parser.export_csv(csv_path, redact_pii=True)
    parser.export_json(json_path, redact_pii=True)
    assert "Alice" not in csv_path.read_text()
    assert "0001" not in json_path.read_text()
    payload = json.loads(json_path.read_text())
    assert payload["summary"]["account_id"] == "***REDACTED***"
    assert payload["transactions"][0]["amount"] == "1.234"
    assert parser.parse().iloc[0]["account_id"] == "0001"


class _Schema:
    def __init__(self):
        self.names = ["amount", "reference"]

    def __iter__(self):
        return iter(
            [
                SimpleNamespace(name="amount", nullable=False),
                SimpleNamespace(name="reference", nullable=True),
            ]
        )


def _fake_arrow(monkeypatch):
    batches = []

    class Writer:
        def __init__(self, path, schema, **kwargs):
            self.path = path

        def __enter__(self):
            self.path.write_bytes(b"PAR1")
            return self

        def __exit__(self, *args):
            return False

        def write_table(self, table):
            batches.append(list(table))

    pa = SimpleNamespace(
        Table=SimpleNamespace(from_pylist=lambda rows, **kwargs: list(rows))
    )
    pq = SimpleNamespace(ParquetWriter=Writer)
    monkeypatch.setattr(
        "bankstatementparser.export.parquet.importlib.import_module",
        lambda name: pa if name == "pyarrow" else pq,
    )
    return batches


def test_streaming_parquet_batches_before_consuming_more_input(
    tmp_path, monkeypatch
) -> None:
    batches = _fake_arrow(monkeypatch)

    def records():
        for index in range(5):
            assert len(batches) == index // 2
            yield {"amount": Decimal(index), "reference": "Alice"}

    output = tmp_path / "stream.parquet"
    assert (
        export_parquet_stream(
            records(), output, schema=_Schema(), batch_size=2, redact_pii=True
        )
        == 5
    )
    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert all(
        row["reference"] == "***REDACTED***"
        for batch in batches
        for row in batch
    )
    assert list(tmp_path.iterdir()) == [output]
    assert export_parquet_stream([], output, schema=_Schema()) == 0
    schema = _Schema()
    schema.names = ["amount", "amount"]
    with pytest.raises(ValueError, match="unique"):
        export_parquet_stream([], output, schema=schema)


@pytest.mark.parametrize(
    "record", [{"amount": 1, "extra": "lost"}, {"reference": "missing amount"}]
)
def test_streaming_parquet_schema_errors_preserve_destination(
    tmp_path, monkeypatch, record
) -> None:
    _fake_arrow(monkeypatch)
    output = tmp_path / "existing.parquet"
    output.write_bytes(b"original")
    with pytest.raises(ValueError, match="Parquet"):
        export_parquet_stream([record], output, schema=_Schema())
    assert output.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [output]


def test_streaming_parquet_generator_failure_is_atomic(
    tmp_path, monkeypatch
) -> None:
    _fake_arrow(monkeypatch)
    output = tmp_path / "existing.parquet"
    output.write_bytes(b"original")

    def broken():
        yield {"amount": Decimal("1")}
        raise RuntimeError("failed after one batch")

    with pytest.raises(RuntimeError, match="one batch"):
        export_parquet_stream(broken(), output, schema=_Schema(), batch_size=1)
    assert output.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [output]


def test_streaming_parquet_configuration_and_missing_engine(
    tmp_path, monkeypatch
) -> None:
    for limit in (0, -1, 2.5, True, float("inf")):
        with pytest.raises(ValueError, match="positive"):
            export_parquet_stream(
                [], tmp_path / "out", schema=_Schema(), batch_size=limit
            )

    def missing(name):
        raise ImportError("not installed")

    monkeypatch.setattr(
        "bankstatementparser.export.parquet.importlib.import_module", missing
    )
    with pytest.raises(ImportError, match="Install bankstatementparser"):
        export_parquet_stream([], tmp_path / "out", schema=_Schema())


def test_real_streaming_parquet_decimal_schema_and_redaction(tmp_path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    schema = pa.schema(
        [
            pa.field("amount", pa.decimal128(38, 3), nullable=False),
            pa.field("reference", pa.string()),
        ]
    )
    output = tmp_path / "real.parquet"
    rows = [
        {"amount": Decimal("1.2")},
        {"amount": Decimal("0.001"), "reference": "Alice"},
    ]
    assert (
        export_parquet_stream(
            rows, output, schema=schema, batch_size=1, redact_pii=True
        )
        == 2
    )
    assert pq.read_table(output).to_pylist() == [
        {"amount": Decimal("1.200"), "reference": None},
        {"amount": Decimal("0.001"), "reference": "***REDACTED***"},
    ]
    before = output.read_bytes()
    with pytest.raises(pa.ArrowInvalid):
        export_parquet_stream(
            [{"amount": Decimal("0.0001")}], output, schema=schema
        )
    assert output.read_bytes() == before


@pytest.mark.parametrize("show_pii", [False, True])
def test_cli_streaming_csv_uses_stable_columns_and_lazy_parser(
    tmp_path, show_pii
) -> None:
    source = tmp_path / "input.xml"
    source.write_text(
        '<Document><Stmt><Ntry><Amt Ccy="EUR">1</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry><Ntry><Amt Ccy="EUR">2</Amt><CdtDbtInd>CRDT</CdtDbtInd><AcctSvcrRef>late-reference</AcctSvcrRef></Ntry></Stmt></Document>'
    )
    output = tmp_path / "output.csv"
    with (
        patch(
            "bankstatementparser.cli.CamtParser", wraps=CamtParser
        ) as parser,
        patch(
            "pandas.DataFrame", side_effect=AssertionError("per-row DataFrame")
        ),
    ):
        BankStatementCLI().parse_camt(
            source, output, streaming=True, show_pii=show_pii
        )
    assert parser.call_args.kwargs["lazy"] is True
    with output.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert None not in rows[1]
    assert [row["Amount"] for row in rows] == ["1", "2"]
    assert rows[0]["AcctSvcrRef"] == ""
    assert rows[1]["AcctSvcrRef"] == (
        "late-reference" if show_pii else "***REDACTED***"
    )


def test_cli_streaming_failure_preserves_destination(tmp_path) -> None:
    source = tmp_path / "bad.xml"
    source.write_text(
        '<Document><Stmt><Ntry><Amt Ccy="EUR">1</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry><Ntry></Ntry></Stmt></Document>'
    )
    output = tmp_path / "output.csv"
    output.write_text("original")
    with pytest.raises(SystemExit):
        BankStatementCLI().parse_camt(source, output, streaming=True)
    assert output.read_text() == "original"
    assert not Path(str(output) + ".tmp").exists()


def test_hybrid_json_masks_provenance_diagnostics_and_audit_history() -> None:
    from dataclasses import replace

    from bankstatementparser import Transaction
    from bankstatementparser.hybrid.orchestrator import IngestResult
    from bankstatementparser.hybrid.verification import verify_balance

    transaction = Transaction(
        amount=Decimal("1.234"),
        currency="KWD",
        description="Alice",
        source="/private/Alice.csv",
        raw_source_text="Alice original payment",
        counterparty="Alice",
    )
    verification = replace(
        verify_balance(
            [transaction], opening_balance=None, closing_balance=None
        ),
        message="Alice balance",
    )
    result = IngestResult(
        source_method="deterministic",
        source_format="csv",
        transactions=(transaction,),
        verification=verification,
        warnings=("Alice warning",),
        audit_trail=({"before": "Alice", "operator": "Bob"},),
    )
    payload = result.to_json(redact_pii=True)
    assert "Alice" not in payload
    assert "Bob" not in payload
    decoded = json.loads(payload)
    assert decoded["transactions"][0]["amount"] == "1.234"
    assert decoded["transactions"][0]["source_method"] == "deterministic"
    assert decoded["audit_trail"] == [{"redacted": True}]
    assert "Alice" in result.to_json()


@pytest.mark.parametrize("format_name", ["hledger", "beancount"])
def test_ledger_redaction_preserves_amounts_without_posting_identifiers(
    format_name,
) -> None:
    from datetime import date

    from bankstatementparser import Transaction
    from bankstatementparser.export import to_beancount, to_hledger

    transaction = Transaction(
        amount=Decimal("1.234"),
        currency="KWD",
        booking_date=date(2026, 1, 1),
        description="Alice payment",
        counterparty="Alice",
        category="Alice expense",
    )
    exporter = to_hledger if format_name == "hledger" else to_beancount
    text = exporter(
        [transaction],
        account="Assets:Bank123",
        contra_account="Expenses:Alice",
        redact_pii=True,
    )
    assert "Alice" not in text
    assert "Bank123" not in text
    assert "1.234" in text
    assert "2026-01-01" in text
    assert "Assets:Redacted" in text
    assert "Expenses:Redacted" in text


def test_excel_redacts_every_sheet(tmp_path, monkeypatch) -> None:
    import sys
    from unittest.mock import MagicMock

    import pandas as pd

    monkeypatch.setitem(sys.modules, "openpyxl", SimpleNamespace())
    monkeypatch.setattr(pd, "ExcelWriter", MagicMock())
    sheets = {}

    def capture(frame, writer, *, sheet_name, index):
        sheets[sheet_name] = frame.to_dict("records")

    monkeypatch.setattr(pd.DataFrame, "to_excel", capture)
    parser = CamtParser.from_string(
        '<Document><Stmt><Id>Alice-statement</Id><Acct><Id><IBAN>Alice-account</IBAN></Id></Acct><Bal><Tp><Cd>OPBD</Cd></Tp><Amt Ccy="EUR">1</Amt><CdtDbtInd>CRDT</CdtDbtInd></Bal><Ntry><Amt Ccy="EUR">1</Amt><CdtDbtInd>CRDT</CdtDbtInd><RmtInf><Ustrd>Alice payment</Ustrd></RmtInf></Ntry></Stmt></Document>'
    )
    parser.camt_to_excel(str(tmp_path / "masked.xlsx"), redact_pii=True)
    assert set(sheets) == {"Balances", "Transactions", "Stats"}
    assert "Alice" not in str(sheets)
    assert sheets["Transactions"][0]["Amount"] == Decimal("1")


@pytest.mark.parametrize("show_pii", [False, True])
def test_cli_eager_csv_respects_explicit_pii_choice(
    tmp_path, show_pii
) -> None:
    source = tmp_path / "input.xml"
    source.write_text(
        '<Document><Stmt><Acct><Id><IBAN>Alice-account</IBAN></Id></Acct><Ntry><Amt Ccy="EUR">1</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry></Stmt></Document>'
    )
    output = tmp_path / "output.csv"
    BankStatementCLI().parse_camt(source, output, show_pii=show_pii)
    with output.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["AccountId"] == (
        "Alice-account" if show_pii else "***REDACTED***"
    )
    assert rows[0]["NumTransactions"] == "1"
