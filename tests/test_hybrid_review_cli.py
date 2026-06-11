# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the v0.0.6 ``--type review`` CLI subcommand (#45)."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from bankstatementparser import BoundingBox, Transaction, cli
from bankstatementparser.hybrid.orchestrator import IngestResult
from bankstatementparser.hybrid.verification import (
    BalanceVerification,
    VerificationStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tx(
    amount: str,
    desc: str,
    *,
    day: str = "2026-04-01",
    confidence: float = 0.9,
    bbox: BoundingBox | None = None,
) -> Transaction:
    return Transaction(
        amount=Decimal(amount),
        booking_date=day,  # type: ignore[arg-type]
        description=desc,
        currency="GBP",
        source_method="llm",
        confidence=confidence,
        source_bbox=bbox,
    )


def _make_discrepancy_result(
    *, transactions: list[Transaction]
) -> IngestResult:
    verification = BalanceVerification(
        status=VerificationStatus.DISCREPANCY,
        opening_balance=Decimal("500.00"),
        closing_balance=Decimal("600.00"),
        total_credits=Decimal("100.00"),
        total_debits=Decimal("0.00"),
        expected_delta=Decimal("100.00"),
        actual_delta=Decimal("100.00"),
        discrepancy=Decimal("0.00"),
        message="forced for tests",
    )
    return IngestResult(
        source_method="llm",
        source_format="pdf",
        transactions=transactions,
        verification=verification,
        warnings=[],
    )


def _write_result(result: IngestResult, tmp_path: Path) -> Path:
    payload_path = tmp_path / "result.json"
    payload_path.write_text(result.to_json(), encoding="utf-8")
    return payload_path


def _drive_inputs(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    """Replace ``builtins.input`` with a deterministic iterator.

    Each ``input(...)`` call consumes the next answer from the
    list. Raises ``EOFError`` when the list is exhausted, which
    the CLI treats as "quit early".
    """
    iterator: Iterator[str] = iter(answers)

    def fake_input(prompt: str = "") -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise EOFError("input list exhausted") from exc

    monkeypatch.setattr("builtins.input", fake_input)


# ---------------------------------------------------------------------------
# Happy paths — accept / skip / delete / edit / quit
# ---------------------------------------------------------------------------


def test_review_accept_keeps_all_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    txs = [_tx("100.00", "Salary"), _tx("-30.00", "Coffee")]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    _drive_inputs(monkeypatch, ["a", "a"])

    cli.BankStatementCLI().run_review(payload_path)

    written = json.loads(payload_path.read_text())
    assert len(written["transactions"]) == 2
    actions = [e["action"] for e in written["audit_trail"]]
    assert actions == ["accept", "accept"]
    captured = capsys.readouterr()
    assert "Review complete" in captured.out
    assert "2 rows" in captured.out


def test_review_delete_drops_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    txs = [_tx("100.00", "Salary"), _tx("-30.00", "Coffee")]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    _drive_inputs(monkeypatch, ["d", "a"])

    cli.BankStatementCLI().run_review(payload_path)

    written = json.loads(payload_path.read_text())
    assert len(written["transactions"]) == 1
    assert written["transactions"][0]["description"] == "Coffee"
    actions = [e["action"] for e in written["audit_trail"]]
    assert actions == ["delete", "accept"]
    deleted = next(
        e for e in written["audit_trail"] if e["action"] == "delete"
    )
    assert "deleted_hash" in deleted


def test_review_skip_keeps_row_with_skip_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    txs = [_tx("100.00", "Salary")]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    _drive_inputs(monkeypatch, ["s"])

    cli.BankStatementCLI().run_review(payload_path)
    written = json.loads(payload_path.read_text())
    assert len(written["transactions"]) == 1
    assert written["audit_trail"][0]["action"] == "skip"


def test_review_quit_keeps_unreviewed_rows_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    txs = [
        _tx("100.00", "Salary"),
        _tx("-30.00", "Coffee"),
        _tx("-7.40", "TFL"),
    ]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    # Accept first row, then quit — last two should be preserved
    # untouched, audit shows "quit" action.
    _drive_inputs(monkeypatch, ["a", "q"])

    cli.BankStatementCLI().run_review(payload_path)

    written = json.loads(payload_path.read_text())
    assert len(written["transactions"]) == 3  # all preserved
    actions = [e["action"] for e in written["audit_trail"]]
    assert actions == ["accept", "quit"]
    out = capsys.readouterr().out
    assert "quit by operator" in out


def test_review_edit_updates_description_and_amount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    txs = [_tx("100.00", "Salary")]
    original_hash = txs[0].transaction_hash
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    # action=e, then new description, then new amount
    _drive_inputs(
        monkeypatch,
        ["e", "Salary ACME CORP", "2500.00"],
    )

    cli.BankStatementCLI().run_review(payload_path)

    written = json.loads(payload_path.read_text())
    assert len(written["transactions"]) == 1
    assert written["transactions"][0]["description"] == "Salary ACME CORP"
    assert Decimal(written["transactions"][0]["amount"]) == Decimal("2500.00")
    edit_entry = written["audit_trail"][0]
    assert edit_entry["action"] == "edit"
    assert edit_entry["before_hash"] == original_hash
    assert edit_entry["after_hash"] != original_hash


def test_review_edit_keeps_defaults_when_operator_presses_enter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    txs = [_tx("100.00", "Salary")]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    # Empty strings = "keep current value"
    _drive_inputs(monkeypatch, ["e", "", ""])

    cli.BankStatementCLI().run_review(payload_path)

    written = json.loads(payload_path.read_text())
    assert written["transactions"][0]["description"] == "Salary"
    assert Decimal(written["transactions"][0]["amount"]) == Decimal("100.00")


def test_review_edit_falls_back_to_original_on_bad_amount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    txs = [_tx("100.00", "Salary")]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    _drive_inputs(monkeypatch, ["e", "Salary v2", "not-a-number"])

    cli.BankStatementCLI().run_review(payload_path)

    written = json.loads(payload_path.read_text())
    # Bad input -> original row preserved unchanged
    assert written["transactions"][0]["description"] == "Salary"
    assert Decimal(written["transactions"][0]["amount"]) == Decimal("100.00")
    assert "edit aborted" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_review_invalid_action_reprompts_until_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    txs = [_tx("100.00", "Salary")]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    # invalid, invalid, then valid
    _drive_inputs(monkeypatch, ["x", "?", "a"])

    cli.BankStatementCLI().run_review(payload_path)
    out = capsys.readouterr().out
    assert "Please enter one of" in out


def test_review_no_verification_section_skipped(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = IngestResult(
        source_method="deterministic",
        source_format="camt",
        transactions=[_tx("100.00", "Salary")],
        verification=None,
    )
    payload_path = _write_result(result, tmp_path)
    cli.BankStatementCLI().run_review(payload_path)
    captured = capsys.readouterr().out
    assert "nothing to review" in captured


def test_review_verified_status_skipped(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verification = BalanceVerification(
        status=VerificationStatus.VERIFIED,
        opening_balance=Decimal("0"),
        closing_balance=Decimal("100"),
        total_credits=Decimal("100"),
        total_debits=Decimal("0"),
        expected_delta=Decimal("100"),
        actual_delta=Decimal("100"),
        discrepancy=Decimal("0"),
        message="ok",
    )
    result = IngestResult(
        source_method="llm",
        source_format="pdf",
        transactions=[_tx("100.00", "Salary")],
        verification=verification,
    )
    payload_path = _write_result(result, tmp_path)
    cli.BankStatementCLI().run_review(payload_path)
    captured = capsys.readouterr().out
    assert "VERIFIED" in captured
    assert "nothing to review" in captured


def test_review_corrupt_json_exits_with_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload_path = tmp_path / "broken.json"
    payload_path.write_text("not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.BankStatementCLI().run_review(payload_path)
    assert "cannot load" in capsys.readouterr().out


def test_review_writes_to_explicit_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    txs = [_tx("100.00", "Salary")]
    input_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    output_path = tmp_path / "out.json"
    _drive_inputs(monkeypatch, ["a"])

    cli.BankStatementCLI().run_review(input_path, output_path)

    # Original input untouched, output written separately
    assert json.loads(input_path.read_text())["audit_trail"] == []
    assert (
        json.loads(output_path.read_text())["audit_trail"][0]["action"]
        == "accept"
    )


def test_review_renders_bbox_and_raw_source_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bbox = BoundingBox(x0=0.05, y0=0.4, x1=0.95, y1=0.45)
    tx = Transaction(
        amount=Decimal("100.00"),
        booking_date="2026-04-01",  # type: ignore[arg-type]
        description="Salary",
        currency="GBP",
        source_method="llm",
        confidence=0.9,
        source_bbox=bbox,
        raw_source_text="raw context for review UI",
    )
    payload_path = _write_result(
        _make_discrepancy_result(transactions=[tx]), tmp_path
    )
    _drive_inputs(monkeypatch, ["a"])

    cli.BankStatementCLI().run_review(payload_path)

    out = capsys.readouterr().out
    assert "source bbox" in out
    assert "page 0" in out
    assert "raw context for review UI" in out


def test_review_edit_then_accept_next_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit on row 0, accept on row 1 — exercises the edit→continue branch."""
    txs = [_tx("100.00", "Salary"), _tx("-30.00", "Coffee")]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    _drive_inputs(monkeypatch, ["e", "Salary edited", "150.00", "a"])

    cli.BankStatementCLI().run_review(payload_path)

    written = json.loads(payload_path.read_text())
    assert len(written["transactions"]) == 2
    assert written["transactions"][0]["description"] == "Salary edited"
    assert written["transactions"][1]["description"] == "Coffee"
    actions = [e["action"] for e in written["audit_trail"]]
    assert actions == ["edit", "accept"]


def test_review_renders_row_without_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Confidence-less row exercises the `if confidence is not None` branch."""
    tx = Transaction(
        amount=Decimal("100.00"),
        booking_date="2026-04-01",  # type: ignore[arg-type]
        description="Deterministic row",
        currency="GBP",
        # No confidence — typical for deterministic rows
    )
    payload_path = _write_result(
        _make_discrepancy_result(transactions=[tx]), tmp_path
    )
    _drive_inputs(monkeypatch, ["a"])

    cli.BankStatementCLI().run_review(payload_path)

    out = capsys.readouterr().out
    assert "Deterministic row" in out
    assert "confidence:" not in out  # the line should be skipped


def test_review_eof_during_action_treated_as_quit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    txs = [_tx("100.00", "Salary"), _tx("-30.00", "Coffee")]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    # No answers — first input() raises EOFError immediately
    _drive_inputs(monkeypatch, [])

    cli.BankStatementCLI().run_review(payload_path)
    out = capsys.readouterr().out
    assert "quit by operator" in out


def test_review_missing_extra_exits_with_install_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload_path = tmp_path / "result.json"
    payload_path.write_text("{}", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "bankstatementparser.hybrid", None)

    with pytest.raises(SystemExit):
        cli.BankStatementCLI().run_review(payload_path)
    captured = capsys.readouterr().out
    assert "[hybrid]" in captured


# ---------------------------------------------------------------------------
# Dispatch through run()
# ---------------------------------------------------------------------------


def test_cli_run_dispatches_to_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    txs = [_tx("100.00", "Salary")]
    payload_path = _write_result(
        _make_discrepancy_result(transactions=txs), tmp_path
    )
    _drive_inputs(monkeypatch, ["a"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bankstatementparser",
            "--type",
            "review",
            "--input",
            str(payload_path),
        ],
    )
    cli.BankStatementCLI().run()
    written = json.loads(payload_path.read_text())
    assert written["audit_trail"][0]["action"] == "accept"
