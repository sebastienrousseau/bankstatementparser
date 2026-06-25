#!/usr/bin/env python3
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Run the LLM-extraction accuracy eval against ground-truth cases.

Usage::

    # Real model (reads BSP_HYBRID_MODEL / BSP_HYBRID_API_BASE):
    python scripts/run_llm_eval.py

    # Specific model and threshold:
    python scripts/run_llm_eval.py --model ollama/llama3 --min-f1 0.9

    # Harness self-check without any model (perfect mock answers):
    python scripts/run_llm_eval.py --mock

Exit code is 1 when the mean F1 falls below ``--min-f1`` or any case
errors, so CI can surface a regression. The CI job wraps this in
``continue-on-error: true`` — accuracy drift warns, it never blocks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser.hybrid.evaluation import (  # noqa: E402
    EvalCase,
    EvalScore,
    load_eval_cases,
    score_extraction,
    summarize_scores,
)
from bankstatementparser.hybrid.llm_extractor import (  # noqa: E402
    LLMExtractor,
)

DEFAULT_CASES_DIR = REPO_ROOT / "tests" / "test_data" / "eval"


def _mock_completion_for(case: EvalCase) -> Any:
    """Build a completion_fn that answers a case perfectly.

    Used by ``--mock`` to verify the harness end-to-end (case
    loading, extraction parsing, scoring, reporting) without a model.
    A healthy harness scores 1.0 everywhere in mock mode.
    """
    payload = {
        "account_id": case.account_id,
        "currency": case.currency,
        "opening_balance": (
            str(case.opening_balance)
            if case.opening_balance is not None
            else None
        ),
        "closing_balance": (
            str(case.closing_balance)
            if case.closing_balance is not None
            else None
        ),
        "transactions": [
            {
                "booking_date": (
                    tx.booking_date.isoformat() if tx.booking_date else None
                ),
                "amount": str(tx.amount),
                "description": tx.description,
                "confidence": 1.0,
            }
            for tx in case.transactions
        ],
    }

    def completion(**_kwargs: Any) -> dict[str, Any]:
        """Return the case's perfect answer as a completion response."""
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    return completion


def _run_case(case: EvalCase, *, args: argparse.Namespace) -> EvalScore:
    """Extract and score a single eval case using the configured model."""
    if args.mock:
        extractor = LLMExtractor(completion_fn=_mock_completion_for(case))
    else:
        extractor = LLMExtractor(model=args.model)
    result = extractor.extract(case.statement_text)
    return score_extraction(
        case,
        transactions=result.transactions,
        account_id=result.account_id,
        currency=result.currency,
        opening_balance=result.opening_balance,
        closing_balance=result.closing_balance,
    )


def _flag(value: bool | None) -> str:
    """Render a tri-state correctness flag for printing."""
    if value is None:
        return "-"
    return "ok" if value else "WRONG"


def _print_score(score: EvalScore) -> None:
    """Print the per-case score breakdown to stdout."""
    print(f"\n=== {score.case_name} ===")
    print(
        f"  rows: {score.matched}/{score.expected_count} matched "
        f"({score.actual_count} extracted)"
    )
    print(
        f"  precision {score.precision:.2f}  "
        f"recall {score.recall:.2f}  f1 {score.f1:.2f}"
    )
    if score.date_accuracy is not None:
        print(f"  date accuracy:        {score.date_accuracy:.2f}")
    if score.description_accuracy is not None:
        print(f"  description accuracy: {score.description_accuracy:.2f}")
    print(
        f"  opening {_flag(score.opening_balance_correct)}  "
        f"closing {_flag(score.closing_balance_correct)}  "
        f"currency {_flag(score.currency_correct)}  "
        f"account {_flag(score.account_id_correct)}"
    )


def main(argv: list[str] | None = None) -> int:
    """Run the eval across all cases and report a pass/fail summary."""
    parser = argparse.ArgumentParser(
        description="LLM extraction accuracy eval"
    )
    parser.add_argument(
        "--cases",
        default=str(DEFAULT_CASES_DIR),
        help=f"Directory of ground-truth cases ({DEFAULT_CASES_DIR})",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LiteLLM model id (default: BSP_HYBRID_MODEL env var)",
    )
    parser.add_argument(
        "--min-f1",
        type=float,
        default=0.8,
        help="Fail (exit 1) when mean F1 falls below this (default 0.8)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Answer every case perfectly without calling a model "
        "(harness self-check)",
    )
    args = parser.parse_args(argv)

    if not args.mock and not (
        args.model or os.environ.get("BSP_HYBRID_MODEL")
    ):
        print(
            "No model configured: set BSP_HYBRID_MODEL or pass "
            "--model (or --mock for a harness self-check)."
        )
        return 2

    cases = load_eval_cases(args.cases)
    print(
        f"Running {len(cases)} eval case(s) "
        f"[{'mock' if args.mock else (args.model or os.environ['BSP_HYBRID_MODEL'])}]"
    )

    scores: list[EvalScore] = []
    errors = 0
    for case in cases:
        try:
            score = _run_case(case, args=args)
        except Exception as exc:
            errors += 1
            print(f"\n=== {case.name} ===\n  ERROR: {exc}")
            continue
        scores.append(score)
        _print_score(score)

    if not scores:
        print("\nAll cases errored; no scores to summarize.")
        return 1

    summary = summarize_scores(scores)
    print(
        f"\n--- Summary ({summary.case_count} case(s), {errors} error(s)) ---"
    )
    print(
        f"  mean precision {summary.mean_precision:.3f}  "
        f"mean recall {summary.mean_recall:.3f}  "
        f"mean f1 {summary.mean_f1:.3f}"
    )
    print(f"  worst case: {summary.worst_case} (f1 {summary.worst_f1:.3f})")

    if errors or summary.mean_f1 < args.min_f1:
        print(
            f"\nFAIL: mean f1 {summary.mean_f1:.3f} < {args.min_f1} "
            f"or {errors} case error(s)."
        )
        return 1
    print(f"\nPASS: mean f1 {summary.mean_f1:.3f} >= {args.min_f1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
