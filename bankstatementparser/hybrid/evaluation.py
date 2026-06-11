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

"""Accuracy scoring for the LLM extraction path.

The golden-file suite pins the deterministic parsers, but LLM
extraction had no accuracy regression coverage — every prompt or
model tweak was a silent gamble. This module is the pure, fully
tested half of the eval harness: it compares an extraction result
against a ground-truth statement and produces deterministic scores.
The LLM-calling half lives in ``scripts/run_llm_eval.py`` and runs
as a non-blocking CI job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Union

from ..transaction_models import Transaction, normalize_description

PathLike = Union[str, Path]


class EvalCaseError(ValueError):
    """Raised when a ground-truth eval case file is malformed."""


@dataclass(frozen=True)
class ExpectedTransaction:
    """One ground-truth transaction row."""

    amount: Decimal
    booking_date: Optional[date] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class EvalCase:
    """A ground-truth statement: raw text plus expected extraction."""

    name: str
    statement_text: str
    account_id: Optional[str]
    currency: Optional[str]
    opening_balance: Optional[Decimal]
    closing_balance: Optional[Decimal]
    transactions: tuple[ExpectedTransaction, ...]


@dataclass(frozen=True)
class EvalScore:
    """Deterministic accuracy scores for one eval case.

    Row matching is greedy on exact amount (then booking date as a
    tie-breaker), so ``precision``/``recall``/``f1`` measure whether
    the model found the right *rows*; the per-field accuracies
    measure whether the matched rows carry the right *values*.
    """

    case_name: str
    expected_count: int
    actual_count: int
    matched: int
    precision: float
    recall: float
    f1: float
    date_accuracy: Optional[float]
    description_accuracy: Optional[float]
    opening_balance_correct: Optional[bool]
    closing_balance_correct: Optional[bool]
    currency_correct: Optional[bool]
    account_id_correct: Optional[bool]


@dataclass(frozen=True)
class EvalSummary:
    """Aggregate scores across all eval cases."""

    case_count: int
    mean_f1: float
    mean_precision: float
    mean_recall: float
    worst_case: str
    worst_f1: float


def _to_decimal(value: object, *, context: str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise EvalCaseError(f"Invalid decimal {value!r} in {context}") from exc


def _optional_decimal(value: object, *, context: str) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    return _to_decimal(value, context=context)


def _optional_date(value: object, *, context: str) -> Optional[date]:
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise EvalCaseError(f"Invalid date {value!r} in {context}") from exc


def load_eval_case(path: PathLike) -> EvalCase:
    """Load one ground-truth case from its JSON file.

    Args:
        path: Path to a case file. See ``tests/test_data/eval/`` for
            the schema: ``name``, ``statement_text``, and an
            ``expected`` object with balances and transactions.

    Returns:
        The parsed :class:`EvalCase`.

    Raises:
        EvalCaseError: If the file is not valid JSON or required
            fields are missing or malformed.
    """
    case_path = Path(path)
    try:
        payload = json.loads(case_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalCaseError(f"Invalid JSON in {case_path}: {exc}") from exc

    name = payload.get("name") or case_path.stem
    statement_text = payload.get("statement_text")
    if not statement_text or not str(statement_text).strip():
        raise EvalCaseError(f"{case_path}: 'statement_text' is required")
    expected = payload.get("expected")
    if not isinstance(expected, dict):
        raise EvalCaseError(f"{case_path}: 'expected' object is required")
    raw_txs = expected.get("transactions")
    if not isinstance(raw_txs, list) or not raw_txs:
        raise EvalCaseError(
            f"{case_path}: 'expected.transactions' must be a non-empty list"
        )

    transactions = []
    for index, item in enumerate(raw_txs):
        context = f"{case_path} transaction {index}"
        if not isinstance(item, dict) or "amount" not in item:
            raise EvalCaseError(f"{context}: 'amount' is required")
        transactions.append(
            ExpectedTransaction(
                amount=_to_decimal(item["amount"], context=context),
                booking_date=_optional_date(
                    item.get("booking_date"), context=context
                ),
                description=item.get("description"),
            )
        )

    return EvalCase(
        name=str(name),
        statement_text=str(statement_text),
        account_id=expected.get("account_id"),
        currency=expected.get("currency"),
        opening_balance=_optional_decimal(
            expected.get("opening_balance"),
            context=f"{case_path} opening_balance",
        ),
        closing_balance=_optional_decimal(
            expected.get("closing_balance"),
            context=f"{case_path} closing_balance",
        ),
        transactions=tuple(transactions),
    )


def load_eval_cases(directory: PathLike) -> list[EvalCase]:
    """Load every ``*.json`` case in a directory, sorted by name.

    Args:
        directory: Directory containing case files.

    Returns:
        All parsed cases.

    Raises:
        EvalCaseError: If the directory contains no case files or
            any case is malformed.
    """
    root = Path(directory)
    paths = sorted(root.glob("*.json"))
    if not paths:
        raise EvalCaseError(f"No eval cases found in {root}")
    return [load_eval_case(path) for path in paths]


def _match_rows(
    expected: tuple[ExpectedTransaction, ...],
    actual: list[Transaction],
) -> list[tuple[ExpectedTransaction, Transaction]]:
    """Greedily pair expected and actual rows on exact amount.

    A row with a matching amount *and* booking date is preferred over
    an amount-only match so two same-amount rows on different days
    pair up correctly.
    """
    unmatched = list(actual)
    pairs: list[tuple[ExpectedTransaction, Transaction]] = []
    for exp in expected:
        best: Optional[Transaction] = None
        for tx in unmatched:
            if tx.amount != exp.amount:
                continue
            if (
                exp.booking_date is not None
                and tx.booking_date == exp.booking_date
            ):
                best = tx
                break
            if best is None:
                best = tx
        if best is not None:
            unmatched.remove(best)
            pairs.append((exp, best))
    return pairs


def _description_matches(
    expected: Optional[str], actual: Optional[str]
) -> bool:
    if not expected:
        return not actual
    if not actual:
        return False
    exp_norm = normalize_description(expected)
    act_norm = normalize_description(actual)
    return exp_norm == act_norm or exp_norm in act_norm or act_norm in exp_norm


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def score_extraction(
    case: EvalCase,
    *,
    transactions: list[Transaction],
    account_id: Optional[str] = None,
    currency: Optional[str] = None,
    opening_balance: Optional[Decimal] = None,
    closing_balance: Optional[Decimal] = None,
) -> EvalScore:
    """Score one extraction result against its ground truth.

    Args:
        case: The ground-truth case.
        transactions: Rows the extractor produced.
        account_id: Extracted account id, if any.
        currency: Extracted currency, if any.
        opening_balance: Extracted opening balance, if any.
        closing_balance: Extracted closing balance, if any.

    Returns:
        An :class:`EvalScore`. Field accuracies are ``None`` when no
        rows matched; statement-level checks are ``None`` when the
        ground truth does not pin that field.
    """
    pairs = _match_rows(case.transactions, transactions)
    matched = len(pairs)
    precision = _ratio(matched, len(transactions))
    recall = _ratio(matched, len(case.transactions))
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    date_accuracy: Optional[float] = None
    description_accuracy: Optional[float] = None
    if matched:
        dates_checked = [
            (exp, tx) for exp, tx in pairs if exp.booking_date is not None
        ]
        if dates_checked:
            date_accuracy = _ratio(
                sum(
                    1
                    for exp, tx in dates_checked
                    if tx.booking_date == exp.booking_date
                ),
                len(dates_checked),
            )
        description_accuracy = _ratio(
            sum(
                1
                for exp, tx in pairs
                if _description_matches(exp.description, tx.description)
            ),
            matched,
        )

    def _check(expected_value: object, actual_value: object) -> Optional[bool]:
        if expected_value is None:
            return None
        return expected_value == actual_value

    return EvalScore(
        case_name=case.name,
        expected_count=len(case.transactions),
        actual_count=len(transactions),
        matched=matched,
        precision=precision,
        recall=recall,
        f1=f1,
        date_accuracy=date_accuracy,
        description_accuracy=description_accuracy,
        opening_balance_correct=_check(case.opening_balance, opening_balance),
        closing_balance_correct=_check(case.closing_balance, closing_balance),
        currency_correct=_check(
            case.currency,
            currency.upper() if currency else None,
        ),
        account_id_correct=_check(case.account_id, account_id),
    )


def summarize_scores(scores: list[EvalScore]) -> EvalSummary:
    """Aggregate per-case scores into one summary.

    Args:
        scores: Per-case scores. Must be non-empty.

    Returns:
        The :class:`EvalSummary` with mean metrics and the worst
        case by F1.

    Raises:
        ValueError: If ``scores`` is empty.
    """
    if not scores:
        raise ValueError("summarize_scores requires at least one score")
    worst = min(scores, key=lambda s: s.f1)
    count = len(scores)
    return EvalSummary(
        case_count=count,
        mean_f1=sum(s.f1 for s in scores) / count,
        mean_precision=sum(s.precision for s in scores) / count,
        mean_recall=sum(s.recall for s in scores) / count,
        worst_case=worst.case_name,
        worst_f1=worst.f1,
    )
