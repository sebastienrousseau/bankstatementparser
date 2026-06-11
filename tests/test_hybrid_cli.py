# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the hybrid `ingest` CLI subcommand."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bankstatementparser import Transaction, cli
from bankstatementparser.hybrid.orchestrator import IngestResult
from bankstatementparser.hybrid.verification import (
    BalanceVerification,
    VerificationStatus,
)


def _make_result(verified: bool = True) -> IngestResult:
    tx = Transaction(
        amount=Decimal("10.00"),
        booking_date="2026-04-01",  # type: ignore[arg-type]
        description="Coffee",
        currency="GBP",
        source_method="llm",
        confidence=0.9,
    )
    verification = BalanceVerification(
        status=VerificationStatus.VERIFIED
        if verified
        else VerificationStatus.DISCREPANCY,
        opening_balance=Decimal("0"),
        closing_balance=Decimal("10"),
        total_credits=Decimal("10"),
        total_debits=Decimal("0"),
        expected_delta=Decimal("10"),
        actual_delta=Decimal("10"),
        discrepancy=Decimal("0"),
        message="ok",
    )
    return IngestResult(
        source_method="llm",
        source_format="pdf",
        transactions=[tx],
        verification=verification,
        warnings=["a warning"],
    )


def test_run_ingest_console_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    file_path = tmp_path / "stmt.pdf"
    file_path.write_text("x")

    instance = cli.BankStatementCLI()

    import bankstatementparser.hybrid as hybrid_pkg

    monkeypatch.setattr(hybrid_pkg, "smart_ingest", lambda _p: _make_result())

    instance.run_ingest(file_path)

    captured = capsys.readouterr()
    assert "Source method: llm" in captured.out
    assert "VERIFIED" in captured.out
    assert "Warning: a warning" in captured.out


def test_run_ingest_writes_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    file_path = tmp_path / "stmt.pdf"
    file_path.write_text("x")
    output_path = tmp_path / "out.csv"

    instance = cli.BankStatementCLI()
    import bankstatementparser.hybrid as hybrid_pkg

    monkeypatch.setattr(hybrid_pkg, "smart_ingest", lambda _p: _make_result())

    instance.run_ingest(file_path, output_path)

    assert output_path.exists()
    text = output_path.read_text()
    assert "transaction_hash" in text
    assert "Coffee" in text
    captured = capsys.readouterr()
    assert "Ingested 1 transactions" in captured.out


def test_run_ingest_handles_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "stmt.pdf"
    file_path.write_text("x")

    instance = cli.BankStatementCLI()
    import bankstatementparser.hybrid as hybrid_pkg

    def boom(_p: Any) -> Any:
        raise RuntimeError("nope")

    monkeypatch.setattr(hybrid_pkg, "smart_ingest", boom)

    with pytest.raises(SystemExit):
        instance.run_ingest(file_path)


def test_run_ingest_no_verification_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    file_path = tmp_path / "stmt.pdf"
    file_path.write_text("x")

    instance = cli.BankStatementCLI()
    import bankstatementparser.hybrid as hybrid_pkg

    tx = Transaction(
        amount=Decimal("10.00"),
        booking_date="2026-04-01",  # type: ignore[arg-type]
        description="Coffee",
    )
    result = IngestResult(
        source_method="deterministic",
        source_format="csv",
        transactions=[tx],
        verification=None,
        warnings=[],
    )
    monkeypatch.setattr(hybrid_pkg, "smart_ingest", lambda _p: result)

    instance.run_ingest(file_path)
    captured = capsys.readouterr()
    assert "Source method: deterministic" in captured.out
    assert "Verification" not in captured.out


def test_cli_run_dispatches_to_ingest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "stmt.pdf"
    file_path.write_text("x")

    import bankstatementparser.hybrid as hybrid_pkg

    monkeypatch.setattr(hybrid_pkg, "smart_ingest", lambda _p: _make_result())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bankstatementparser",
            "--type",
            "ingest",
            "--input",
            str(file_path),
        ],
    )
    cli.BankStatementCLI().run()


def test_run_ingest_missing_extra(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    file_path = tmp_path / "stmt.pdf"
    file_path.write_text("x")

    # Force the import-of-hybrid to fail
    monkeypatch.setitem(sys.modules, "bankstatementparser.hybrid", None)

    instance = cli.BankStatementCLI()
    with pytest.raises(SystemExit):
        instance.run_ingest(file_path)

    captured = capsys.readouterr()
    assert "pip install" in captured.out
    assert "[hybrid]" in captured.out


def test_run_ingest_lazy_importerror_in_smart_ingest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    file_path = tmp_path / "stmt.pdf"
    file_path.write_text("x")

    instance = cli.BankStatementCLI()
    import bankstatementparser.hybrid as hybrid_pkg

    def boom(_p: Any) -> Any:
        raise ImportError("No module named 'pypdf'", name="pypdf")

    monkeypatch.setattr(hybrid_pkg, "smart_ingest", boom)

    with pytest.raises(SystemExit):
        instance.run_ingest(file_path)

    captured = capsys.readouterr()
    assert "PDF ingestion requires" in captured.out
    assert "pypdf" in captured.out
