# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Hypothesis property-based fuzzing for new analytical, forensic, and parsing engines."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from bankstatementparser.analytics import (
    compute_cash_flow_summary,
    detect_anomalies_and_nsf,
    detect_recurring_transactions,
)
from bankstatementparser.field86_parser import parse_field_86
from bankstatementparser.forensics import inspect_pdf_forensics
from bankstatementparser.reconciliation import (
    reconcile_payments_and_statements,
)
from bankstatementparser.transaction_models import Transaction


@given(st.text())
def test_fuzz_parse_field_86(narrative: str) -> None:
    """parse_field_86 must never raise an unhandled exception on any string."""
    res = parse_field_86(narrative)
    assert res is not None
    d = res.to_dict()
    assert isinstance(d, dict)


@given(
    st.lists(
        st.tuples(
            st.dates(),
            st.text(min_size=1, max_size=50),
            st.decimals(
                min_value=Decimal("-1000000.00"),
                max_value=Decimal("1000000.00"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            ),
            st.sampled_from(["EUR", "USD", "GBP", "CHF", "JPY"]),
        ),
        max_size=30,
    )
)
def test_fuzz_analytics_and_cash_flow(
    items: list[tuple[any, str, Decimal, str]],
) -> None:
    """Cash flow and recurring detection must be resilient across arbitrary transaction batches."""
    txs = [
        Transaction(
            date=d.isoformat(),
            description=desc,
            amount=amt,
            currency=curr,
        )
        for d, desc, amt, curr in items
    ]

    metrics = compute_cash_flow_summary(txs)
    assert isinstance(metrics, dict)

    patterns = detect_recurring_transactions(txs)
    assert isinstance(patterns, list)

    anomalies = detect_anomalies_and_nsf(txs)
    assert isinstance(anomalies, list)


@given(
    st.lists(
        st.fixed_dictionaries(
            {
                "EndToEndId": st.text(max_size=20),
                "InstdAmt": st.decimals(
                    min_value=Decimal("0.01"),
                    max_value=Decimal("100000.00"),
                    places=2,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                "CdtrNm": st.text(max_size=30),
            }
        ),
        max_size=15,
    ),
    st.lists(
        st.fixed_dictionaries(
            {
                "end_to_end_id": st.text(max_size=20),
                "amount": st.decimals(
                    min_value=Decimal("-100000.00"),
                    max_value=Decimal("-0.01"),
                    places=2,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                "description": st.text(max_size=40),
            }
        ),
        max_size=15,
    ),
)
def test_fuzz_reconciliation_engine(
    payments: list[dict], statements: list[dict]
) -> None:
    """Reconciliation engine must produce valid reports on arbitrary records."""
    report = reconcile_payments_and_statements(payments, statements)
    assert report is not None
    assert 0.0 <= report.match_rate <= 1.0
    d = report.to_dict()
    assert isinstance(d, dict)


@given(st.binary(max_size=10000))
def test_fuzz_pdf_forensics(pdf_bytes: bytes) -> None:
    """PDF forensics inspector must handle arbitrary binary sequences without crashing."""
    report = inspect_pdf_forensics(pdf_bytes)
    assert report is not None
    assert 0.0 <= report.risk_score <= 1.0
    d = report.to_dict()
    assert "verdict" in d
