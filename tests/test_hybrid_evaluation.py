# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for the LLM-extraction accuracy scoring module."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bankstatementparser.hybrid.evaluation import (
    EvalCase,
    EvalCaseError,
    EvalScore,
    ExpectedTransaction,
    _description_matches,
    _match_rows,
    load_eval_case,
    load_eval_cases,
    score_extraction,
    summarize_scores,
)
from bankstatementparser.transaction_models import Transaction

EVAL_DIR = Path(__file__).resolve().parent / "test_data" / "eval"


def _tx(
    amount: str,
    *,
    booking_date: date | None = None,
    description: str | None = None,
) -> Transaction:
    return Transaction(
        amount=Decimal(amount),
        booking_date=booking_date,
        description=description,
    )


def _case(
    transactions: tuple[ExpectedTransaction, ...],
    **overrides: object,
) -> EvalCase:
    defaults: dict[str, object] = {
        "name": "case",
        "statement_text": "text",
        "account_id": None,
        "currency": None,
        "opening_balance": None,
        "closing_balance": None,
        "transactions": transactions,
    }
    defaults.update(overrides)
    return EvalCase(**defaults)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# Case loading
# ----------------------------------------------------------------------


def test_load_shipped_eval_cases() -> None:
    cases = load_eval_cases(EVAL_DIR)
    assert len(cases) >= 3
    names = [case.name for case in cases]
    assert names == sorted(names)
    for case in cases:
        assert case.statement_text.strip()
        assert case.transactions


def test_load_eval_case_full_fields() -> None:
    case = load_eval_case(EVAL_DIR / "single_currency_checking.json")
    assert case.name == "single_currency_checking"
    assert case.account_id == "GB29NWBK60161331926819"
    assert case.currency == "GBP"
    assert case.opening_balance == Decimal("1000.00")
    assert case.closing_balance == Decimal("2150.00")
    first = case.transactions[0]
    assert first.amount == Decimal("-4.50")
    assert first.booking_date == date(2026, 4, 2)
    assert first.description == "COFFEE SHOP LONDON"


def test_load_eval_case_minimal_fields(tmp_path: Path) -> None:
    path = tmp_path / "minimal.json"
    path.write_text(
        json.dumps(
            {
                "statement_text": "some text",
                "expected": {"transactions": [{"amount": "1.00"}]},
            }
        )
    )
    case = load_eval_case(path)
    assert case.name == "minimal"  # falls back to the file stem
    assert case.account_id is None
    assert case.opening_balance is None
    assert case.closing_balance is None
    tx = case.transactions[0]
    assert tx.booking_date is None
    assert tx.description is None


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("not json {", "Invalid JSON"),
        (json.dumps({"expected": {}}), "statement_text"),
        (
            json.dumps({"statement_text": "   ", "expected": {}}),
            "statement_text",
        ),
        (json.dumps({"statement_text": "x"}), "'expected' object"),
        (
            json.dumps({"statement_text": "x", "expected": {}}),
            "transactions",
        ),
        (
            json.dumps(
                {"statement_text": "x", "expected": {"transactions": []}}
            ),
            "transactions",
        ),
        (
            json.dumps(
                {
                    "statement_text": "x",
                    "expected": {"transactions": ["nope"]},
                }
            ),
            "amount",
        ),
        (
            json.dumps(
                {
                    "statement_text": "x",
                    "expected": {"transactions": [{"amount": "12..3"}]},
                }
            ),
            "Invalid decimal",
        ),
        (
            json.dumps(
                {
                    "statement_text": "x",
                    "expected": {
                        "transactions": [
                            {"amount": "1", "booking_date": "soon"}
                        ]
                    },
                }
            ),
            "Invalid date",
        ),
        (
            json.dumps(
                {
                    "statement_text": "x",
                    "expected": {
                        "opening_balance": "lots",
                        "transactions": [{"amount": "1"}],
                    },
                }
            ),
            "Invalid decimal",
        ),
    ],
)
def test_load_eval_case_rejects_malformed(
    tmp_path: Path, payload: str, match: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(payload)
    with pytest.raises(EvalCaseError, match=match):
        load_eval_case(path)


def test_load_eval_cases_empty_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(EvalCaseError, match="No eval cases"):
        load_eval_cases(tmp_path)


def test_load_eval_case_empty_optional_strings(tmp_path: Path) -> None:
    path = tmp_path / "blanks.json"
    path.write_text(
        json.dumps(
            {
                "statement_text": "x",
                "expected": {
                    "opening_balance": "",
                    "transactions": [{"amount": "1", "booking_date": ""}],
                },
            }
        )
    )
    case = load_eval_case(path)
    assert case.opening_balance is None
    assert case.transactions[0].booking_date is None


# ----------------------------------------------------------------------
# Row matching
# ----------------------------------------------------------------------


def test_match_rows_prefers_same_date_for_equal_amounts() -> None:
    expected = (
        ExpectedTransaction(
            amount=Decimal("-3.20"), booking_date=date(2026, 5, 4)
        ),
    )
    wrong_day = _tx("-3.20", booking_date=date(2026, 5, 3))
    right_day = _tx("-3.20", booking_date=date(2026, 5, 4))
    pairs = _match_rows(expected, [wrong_day, right_day])
    assert pairs == [(expected[0], right_day)]


def test_match_rows_falls_back_to_first_amount_match() -> None:
    expected = (
        ExpectedTransaction(
            amount=Decimal("10"), booking_date=date(2026, 1, 1)
        ),
    )
    first = _tx("10", booking_date=date(2026, 2, 2))
    second = _tx("10", booking_date=date(2026, 3, 3))
    pairs = _match_rows(expected, [first, second])
    assert pairs == [(expected[0], first)]


def test_match_rows_without_expected_date_takes_first_amount() -> None:
    expected = (ExpectedTransaction(amount=Decimal("5")),)
    candidate = _tx("5", booking_date=date(2026, 1, 1))
    pairs = _match_rows(expected, [_tx("7"), candidate])
    assert pairs == [(expected[0], candidate)]


def test_match_rows_unmatched_amount_is_skipped() -> None:
    expected = (ExpectedTransaction(amount=Decimal("99")),)
    assert _match_rows(expected, [_tx("1")]) == []


# ----------------------------------------------------------------------
# Description comparison
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expected", "actual", "outcome"),
    [
        (None, None, True),
        (None, "extra", False),
        ("COFFEE", None, False),
        ("COFFEE SHOP", "coffee shop", True),
        ("COFFEE SHOP", "COFFEE SHOP LONDON", True),
        ("COFFEE SHOP LONDON", "COFFEE SHOP", True),
        ("RENT", "SALARY", False),
    ],
)
def test_description_matches(
    expected: str | None, actual: str | None, outcome: bool
) -> None:
    assert _description_matches(expected, actual) is outcome


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------


def test_score_extraction_perfect() -> None:
    case = _case(
        (
            ExpectedTransaction(
                amount=Decimal("-4.50"),
                booking_date=date(2026, 4, 2),
                description="COFFEE SHOP",
            ),
        ),
        account_id="ACC-1",
        currency="GBP",
        opening_balance=Decimal("10"),
        closing_balance=Decimal("5.50"),
    )
    score = score_extraction(
        case,
        transactions=[
            _tx(
                "-4.50",
                booking_date=date(2026, 4, 2),
                description="Coffee Shop",
            )
        ],
        account_id="ACC-1",
        currency="gbp",
        opening_balance=Decimal("10"),
        closing_balance=Decimal("5.50"),
    )
    assert score.f1 == 1.0
    assert score.date_accuracy == 1.0
    assert score.description_accuracy == 1.0
    assert score.opening_balance_correct is True
    assert score.closing_balance_correct is True
    assert score.currency_correct is True  # case-insensitive
    assert score.account_id_correct is True


def test_score_extraction_no_matches_zero_f1() -> None:
    case = _case((ExpectedTransaction(amount=Decimal("100")),))
    score = score_extraction(case, transactions=[_tx("-1")])
    assert score.matched == 0
    assert score.precision == 0.0
    assert score.recall == 0.0
    assert score.f1 == 0.0
    assert score.date_accuracy is None
    assert score.description_accuracy is None


def test_score_extraction_empty_actual_keeps_precision() -> None:
    case = _case((ExpectedTransaction(amount=Decimal("100")),))
    score = score_extraction(case, transactions=[])
    assert score.precision == 1.0  # nothing extracted, nothing wrong
    assert score.recall == 0.0
    assert score.f1 == 0.0


def test_score_extraction_partial_match_and_wrong_fields() -> None:
    case = _case(
        (
            ExpectedTransaction(
                amount=Decimal("10"),
                booking_date=date(2026, 1, 1),
                description="RENT",
            ),
            ExpectedTransaction(amount=Decimal("20"), description="GAS"),
        ),
        currency="EUR",
        closing_balance=Decimal("30"),
    )
    score = score_extraction(
        case,
        transactions=[
            _tx(
                "10",
                booking_date=date(2026, 2, 2),
                description="SALARY",
            ),
            _tx("999"),
        ],
        currency=None,
        closing_balance=Decimal("31"),
    )
    assert score.matched == 1
    assert score.precision == 0.5
    assert score.recall == 0.5
    assert score.date_accuracy == 0.0
    assert score.description_accuracy == 0.0
    assert score.currency_correct is False
    assert score.closing_balance_correct is False
    assert score.opening_balance_correct is None  # not pinned
    assert score.account_id_correct is None


def test_score_extraction_dates_unpinned_leaves_date_accuracy_none() -> None:
    case = _case(
        (ExpectedTransaction(amount=Decimal("5"), description="FEE"),)
    )
    score = score_extraction(case, transactions=[_tx("5", description="FEE")])
    assert score.matched == 1
    assert score.date_accuracy is None
    assert score.description_accuracy == 1.0


# ----------------------------------------------------------------------
# Aggregation
# ----------------------------------------------------------------------


def _score(name: str, f1: float) -> EvalScore:
    return EvalScore(
        case_name=name,
        expected_count=1,
        actual_count=1,
        matched=1,
        precision=f1,
        recall=f1,
        f1=f1,
        date_accuracy=None,
        description_accuracy=None,
        opening_balance_correct=None,
        closing_balance_correct=None,
        currency_correct=None,
        account_id_correct=None,
    )


def test_summarize_scores() -> None:
    summary = summarize_scores([_score("good", 1.0), _score("bad", 0.5)])
    assert summary.case_count == 2
    assert summary.mean_f1 == 0.75
    assert summary.worst_case == "bad"
    assert summary.worst_f1 == 0.5


def test_summarize_scores_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one score"):
        summarize_scores([])


# ----------------------------------------------------------------------
# Runner script (mock mode is deterministic and model-free)
# ----------------------------------------------------------------------


def test_run_llm_eval_script_mock_mode() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_llm_eval.py"),
            "--mock",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS: mean f1 1.000" in proc.stdout


def test_run_llm_eval_script_requires_model_without_mock() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "BSP_HYBRID_MODEL"}
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_llm_eval.py"),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert proc.returncode == 2
    assert "No model configured" in proc.stdout
