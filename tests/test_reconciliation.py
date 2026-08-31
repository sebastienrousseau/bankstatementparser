# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for Two-Way Payment-to-Statement Cross-Reconciliation Engine."""

from datetime import date
from decimal import Decimal

from bankstatementparser.reconciliation import (
    ReconciliationReport,
    ReconciliationStatus,
    reconcile_payments_and_statements,
)
from bankstatementparser.transaction_models import Transaction


def test_reconcile_exact_end_to_end_id() -> None:
    """Matches payments to statements by exact EndToEndId reference."""
    payments = [
        {
            "EndToEndId": "E2E-2026-001",
            "InstdAmt": Decimal("1500.00"),
            "Currency": "EUR",
            "CdtrNm": "ACME Supplier Ltd",
        },
        {
            "EndToEndId": "E2E-2026-002",
            "InstdAmt": Decimal("2400.00"),
            "Currency": "EUR",
            "CdtrNm": "Global Cloud Services",
        },
    ]

    statements = [
        Transaction(
            booking_date=date(2026, 1, 18),
            description="Transfer Out ref E2E-2026-001 ACME",
            amount=Decimal("-1500.00"),
            currency="EUR",
            reference="E2E-2026-001",
        ),
        Transaction(
            booking_date=date(2026, 1, 19),
            description="Unrelated Bank Charge",
            amount=Decimal("-12.50"),
            currency="EUR",
        ),
    ]

    report = reconcile_payments_and_statements(payments, statements)
    assert isinstance(report, ReconciliationReport)
    assert report.total_payments == 2
    assert report.total_statements == 2
    assert report.matched_count == 1
    assert report.unmatched_payment_count == 1
    assert report.unmatched_statement_count == 1
    assert report.total_reconciled_volume == Decimal("1500.00")

    match = report.matches[0]
    assert match.status == ReconciliationStatus.EXACT_REFERENCE
    assert match.confidence == 1.00
    assert match.amount_difference == Decimal("0.00")

    d = report.to_dict()
    assert d["matched_count"] == 1
    assert d["total_reconciled_volume"] == "1500.00"


def test_reconcile_exact_amount_and_party() -> None:
    """Matches payments to statements by amount and party when reference is omitted."""
    payments = [
        {
            "InstdAmt": Decimal("750.00"),
            "Currency": "EUR",
            "CdtrNm": "Office Supplies GmbH",
        },
    ]
    statements = [
        Transaction(
            booking_date=date(2026, 2, 1),
            description="Payment to Office Supplies GmbH",
            amount=Decimal("-750.00"),
            currency="EUR",
            counterparty="Office Supplies GmbH",
        ),
    ]

    report = reconcile_payments_and_statements(payments, statements)
    assert report.matched_count == 1
    assert (
        report.matches[0].status == ReconciliationStatus.EXACT_AMOUNT_AND_PARTY
    )
    assert report.matches[0].confidence >= 0.95


def test_reconcile_fuzzy_match() -> None:
    """Matches payments to statements using fuzzy name similarity."""
    payments = [
        {
            "InstdAmt": Decimal("320.00"),
            "Currency": "EUR",
            "CdtrNm": "Sebastien Rousseau Consulting",
        },
    ]
    statements = [
        Transaction(
            booking_date=date(2026, 2, 5),
            description="SEBASTIEN ROUSSEAU CNSLT",
            amount=Decimal("-320.00"),
            currency="EUR",
        ),
    ]

    report = reconcile_payments_and_statements(
        payments, statements, fuzzy_threshold=0.60
    )
    assert report.matched_count == 1
    assert report.matches[0].status == ReconciliationStatus.FUZZY_MATCH
    assert report.matches[0].confidence >= 0.60


def test_reconcile_partial_amount_deduction_and_helpers() -> None:
    """Tests partial amount deduction match and conversion helpers."""
    from bankstatementparser.reconciliation import (
        _extract_amount,
        _to_record_dict,
    )

    # Partial amount match (e.g. 1000 payment with 985 statement net settlement due to 15 wire fee)
    payments = [
        {"EndToEndId": "E2E-FEE-99", "InstdAmt": "1000.00", "CdtrNm": "Global"}
    ]
    statements = [
        {
            "end_to_end_id": "E2E-FEE-99",
            "amount": "-985.00",
            "description": "Global net",
        }
    ]
    rep = reconcile_payments_and_statements(payments, statements)
    assert rep.matched_count == 1
    assert rep.partial_deduction_count == 1
    assert (
        rep.matches[0].status == ReconciliationStatus.PARTIAL_AMOUNT_DEDUCTION
    )
    assert rep.matches[0].amount_difference == Decimal("15.00")

    # Conversion helpers
    class ModelObj:
        def to_dict(self) -> dict:
            return {"k": "v"}

    class RawObj:
        def __init__(self) -> None:
            self.attr = "val"

    class StrObj:
        def __str__(self) -> str:
            return "raw_str"

    assert _to_record_dict(ModelObj()) == {"k": "v"}
    assert _to_record_dict(RawObj()) == {"attr": "val"}
    assert _to_record_dict(StrObj()) == {"raw": "raw_str"}

    assert _extract_amount(Decimal("50.00")) == Decimal("50.00")
    assert _extract_amount(100) == Decimal("100")
    assert _extract_amount(25.5) == Decimal("25.5")
    assert _extract_amount("invalid") == Decimal("0.00")
    assert _extract_amount(None) == Decimal("0.00")

    # Pass 3 with zero amount payment
    zero_rep = reconcile_payments_and_statements(
        [{"InstdAmt": "0.00", "CdtrNm": "Zero Inc"}],
        [{"amount": "100.00", "description": "Other"}],
    )
    assert zero_rep.matched_count == 0

    # Pass 3 with same amount but completely different party names (below threshold)
    low_ratio_rep = reconcile_payments_and_statements(
        [{"InstdAmt": "100.00", "CdtrNm": "Alpha Corp"}],
        [{"amount": "100.00", "description": "Zeta Ltd"}],
        fuzzy_threshold=0.90,
    )
    assert low_ratio_rep.matched_count == 0
    assert low_ratio_rep.unmatched_payment_count == 1
