# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for Treasury Cash-Flow Spreading, Cadence Detection, and Anomaly Engine."""

from datetime import date
from decimal import Decimal

from bankstatementparser.analytics import (
    AnalyticsReport,
    AnomalyFinding,
    RecurringCadence,
    analyze_statement_transactions,
    compute_cash_flow_summary,
    detect_anomalies_and_nsf,
    detect_recurring_transactions,
)
from bankstatementparser.transaction_models import Transaction


def test_compute_cash_flow_summary_multi_currency() -> None:
    """Cash flow summary groups totals by currency and computes run rates."""
    txs = [
        Transaction(
            booking_date=date(2026, 1, 15),
            description="Client Payment 1",
            amount=Decimal("5000.00"),
            currency="EUR",
        ),
        Transaction(
            booking_date=date(2026, 1, 20),
            description="Office Rent",
            amount=Decimal("-1200.00"),
            currency="EUR",
        ),
        Transaction(
            booking_date=date(2026, 2, 10),
            description="Consulting Inflow",
            amount=Decimal("3000.00"),
            currency="USD",
        ),
    ]

    metrics_map = compute_cash_flow_summary(txs)
    assert "EUR" in metrics_map
    assert "USD" in metrics_map

    eur = metrics_map["EUR"]
    assert eur.total_inflow == Decimal("5000.00")
    assert eur.total_outflow == Decimal("1200.00")
    assert eur.net_cash_flow == Decimal("3800.00")
    assert eur.credit_count == 1
    assert eur.debit_count == 1
    assert eur.transaction_count == 2
    assert "2026-01" in eur.monthly_inflows

    d = eur.to_dict()
    assert d["total_inflow"] == "5000.00"
    assert d["net_cash_flow"] == "3800.00"


def test_detect_recurring_transactions_cadences() -> None:
    """Detects weekly, monthly, and salary recurring patterns."""
    txs = [
        # Weekly grocery / supplier
        Transaction(
            booking_date=date(2026, 1, 1),
            description="Weekly Supplier Alpha",
            amount=Decimal("-250.00"),
            currency="EUR",
        ),
        Transaction(
            booking_date=date(2026, 1, 8),
            description="Weekly Supplier Alpha",
            amount=Decimal("-250.00"),
            currency="EUR",
        ),
        Transaction(
            booking_date=date(2026, 1, 15),
            description="Weekly Supplier Alpha",
            amount=Decimal("-250.00"),
            currency="EUR",
        ),
        # Monthly Salary
        Transaction(
            booking_date=date(2026, 1, 31),
            description="Monthly Salary Payroll Corp",
            amount=Decimal("4500.00"),
            currency="EUR",
        ),
        Transaction(
            booking_date=date(2026, 2, 28),
            description="Monthly Salary Payroll Corp",
            amount=Decimal("4500.00"),
            currency="EUR",
        ),
    ]

    patterns = detect_recurring_transactions(txs)
    assert len(patterns) >= 2

    # Check weekly pattern
    weekly = next(p for p in patterns if "SUPPLIER" in p.description)
    assert weekly.cadence == RecurringCadence.WEEKLY
    assert weekly.occurrence_count == 3
    assert weekly.amount == Decimal("250.00")
    assert not weekly.is_income

    # Check monthly salary pattern
    salary = next(p for p in patterns if "SALARY" in p.description)
    assert salary.cadence == RecurringCadence.MONTHLY
    assert salary.occurrence_count == 2
    assert salary.amount == Decimal("4500.00")
    assert salary.is_income

    d = salary.to_dict()
    assert d["cadence"] == "MONTHLY"
    assert d["is_income"] is True


def test_detect_anomalies_and_nsf() -> None:
    """Detects NSF returned items and outlier spikes."""
    txs = [
        Transaction(
            booking_date=date(2026, 1, 5),
            description="Monthly Subscription",
            amount=Decimal("-15.00"),
            currency="EUR",
        ),
        Transaction(
            booking_date=date(2026, 1, 10),
            description="OVERDRAFT FEE - RETURNED ITEM",
            amount=Decimal("-35.00"),
            currency="EUR",
        ),
    ]
    # Add multiple regular txs to build median baseline
    for i in range(15):
        txs.append(
            Transaction(
                booking_date=date(2026, 1, 12),
                description=f"Standard Purchase {i}",
                amount=Decimal("-20.00"),
                currency="EUR",
            )
        )
    # Add 1 huge outlier spike
    txs.append(
        Transaction(
            booking_date=date(2026, 1, 15),
            description="Major Equipment Purchase Spike",
            amount=Decimal("-12000.00"),
            currency="EUR",
        )
    )

    findings = detect_anomalies_and_nsf(txs)
    assert any(f.finding_type == "NSF_OVERDRAFT_FEE" for f in findings)
    assert any(f.finding_type == "STATISTICAL_OUTLIER" for f in findings)

    rep = analyze_statement_transactions(txs)
    assert isinstance(rep, AnalyticsReport)
    assert rep.total_transactions_analyzed == len(txs)
    assert "EUR" in rep.summary_by_currency
    d = rep.to_dict()
    assert "summary_by_currency" in d
    assert "anomalies" in d


def test_analytics_all_cadences_and_extractors() -> None:
    """Tests all cadence classifications and edge-case extraction branches."""
    # 1. Daily cadence (1 day interval)
    daily_txs = [
        {
            "date": "2026-01-01",
            "amount": "-5.00",
            "description": "Daily Coffee",
            "currency": "EUR",
        },
        {
            "date": "2026-01-02",
            "amount": "-5.00",
            "description": "Daily Coffee",
            "currency": "EUR",
        },
    ]
    p_daily = detect_recurring_transactions(daily_txs)
    assert p_daily[0].cadence == RecurringCadence.DAILY

    # 2. Bi-Weekly cadence (14 days interval)
    biweekly_txs = [
        {
            "date": "2026-01-01",
            "amount": "2000.00",
            "description": "WAGES BIWEEKLY",
            "currency": "EUR",
        },
        {
            "date": "2026-01-15",
            "amount": "2000.00",
            "description": "WAGES BIWEEKLY",
            "currency": "EUR",
        },
    ]
    p_biweekly = detect_recurring_transactions(biweekly_txs)
    assert p_biweekly[0].cadence == RecurringCadence.BI_WEEKLY
    assert p_biweekly[0].is_income is True

    # 3. Quarterly cadence (90 days interval)
    quarterly_txs = [
        {
            "date": "2026-01-01",
            "amount": "-600.00",
            "description": "Quarterly Tax",
            "currency": "EUR",
        },
        {
            "date": "2026-04-01",
            "amount": "-600.00",
            "description": "Quarterly Tax",
            "currency": "EUR",
        },
    ]
    p_quarterly = detect_recurring_transactions(quarterly_txs)
    assert p_quarterly[0].cadence == RecurringCadence.QUARTERLY

    # 4. Annual cadence (365 days interval)
    annual_txs = [
        {
            "date": "2025-01-01",
            "amount": "-120.00",
            "description": "Annual License",
            "currency": "EUR",
        },
        {
            "date": "2026-01-01",
            "amount": "-120.00",
            "description": "Annual License",
            "currency": "EUR",
        },
    ]
    p_annual = detect_recurring_transactions(annual_txs)
    assert p_annual[0].cadence == RecurringCadence.ANNUAL

    # 5. Irregular cadence (45 days interval)
    irregular_txs = [
        {
            "date": "2026-01-01",
            "amount": "-80.00",
            "description": "Irregular Maintenance",
            "currency": "EUR",
        },
        {
            "date": "2026-02-15",
            "amount": "-80.00",
            "description": "Irregular Maintenance",
            "currency": "EUR",
        },
    ]
    p_irregular = detect_recurring_transactions(irregular_txs)
    assert p_irregular[0].cadence == RecurringCadence.IRREGULAR

    # Test helpers directly
    from datetime import datetime

    from bankstatementparser.analytics import (
        _extract_amount,
        _extract_date,
        _get_attr,
    )

    assert _extract_date(datetime(2026, 3, 1, 10, 0, 0)) == date(2026, 3, 1)
    assert _extract_date("20260301") == date(2026, 3, 1)
    assert _extract_date("01/03/2026") == date(2026, 3, 1)
    assert _extract_date("01-03-2026") == date(2026, 3, 1)
    assert _extract_date("invalid-date") is None
    assert _extract_date(None) is None

    assert _extract_amount(100) == Decimal("100")
    assert _extract_amount(50.5) == Decimal("50.5")
    assert _extract_amount("invalid_amount") == Decimal("0.00")
    assert _extract_amount(None) == Decimal("0.00")

    class DummyObj:
        custom_field = "custom_value"

    assert _get_attr(DummyObj(), "custom_field") == "custom_value"
    assert (
        _get_attr(DummyObj(), "missing_field", default="fallback")
        == "fallback"
    )

    # Explicit credit/debit indicator variations
    c_and_d_txs = [
        {"credit_debit": "CRDT", "amount": "100.00", "currency": "EUR"},
        {"credit_debit": "DBIT", "amount": "50.00", "currency": "EUR"},
        {"credit_debit": "CR", "amount": "20.00", "currency": "EUR"},
        {"credit_debit": "DR", "amount": "10.00", "currency": "EUR"},
    ]
    summary = compute_cash_flow_summary(c_and_d_txs)["EUR"]
    assert summary.credit_count == 2
    assert summary.debit_count == 2

    # Anomaly finding with None amount
    f_none = AnomalyFinding(
        finding_type="TEST",
        severity="LOW",
        description="Desc",
        amount=None,
        currency=None,
        booking_date=None,
        transaction_hash=None,
    )
    assert "amount" not in f_none.to_dict()
