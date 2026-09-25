# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Financial calendar and complete-period balance regression contracts."""

from datetime import date
from decimal import Decimal

import pytest

from bankstatementparser import (
    compute_average_daily_balance,
    compute_cash_flow_summary,
)


def test_daily_balance_weights_booking_days_and_preserves_precision():
    rows = [
        {
            "AccountId": "0001",
            "Currency": "KWD",
            "Amount": "10.123",
            "DrCr": "DBIT",
            "BookgDt": "2024-02-29",
        },
        {
            "AccountId": "0001",
            "Currency": "KWD",
            "Amount": "20.246",
            "DrCr": "CRDT",
            "BookgDt": "2024-02-28",
        },
    ]
    result = compute_average_daily_balance(
        iter(rows),
        opening_balance=Decimal("100"),
        currency="kwd",
        account_id="0001",
        period_start=date(2024, 2, 28),
        period_end=date(2024, 3, 1),
    )
    assert result.day_count == 3
    assert result.closing_balance == Decimal("110.123")
    assert (
        result.average_daily_balance
        == (Decimal("120.246") + Decimal("110.123") * 2) / 3
    )
    assert result.to_dict()["period_start"] == "2024-02-28"
    assert result.to_dict()["closing_balance"] == "110.123"


def test_daily_balance_empty_period_and_repeated_rows():
    kwargs = {
        "opening_balance": Decimal("-1.234"),
        "currency": "EUR",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
    }
    assert compute_average_daily_balance(
        [], **kwargs
    ).average_daily_balance == Decimal("-1.234")
    row = {"date": "2026-01-31", "currency": "EUR", "amount": "-2"}
    result = compute_average_daily_balance([row, row], **kwargs)
    assert result.closing_balance == Decimal("-5.234")
    assert result.average_daily_balance == (Decimal("-1.234") * 31 - 4) / 31


@pytest.mark.parametrize(
    "change",
    [
        {"currency": "USD"},
        {"account_id": "another"},
        {"date": "invalid"},
        {"date": None},
        {"date": "2025-12-31"},
        {"date": "2026-02-01"},
        {"amount": "nan"},
    ],
)
def test_daily_balance_rejects_incomplete_or_mixed_input(change):
    row = {"date": "2026-01-01", "currency": "EUR", "amount": "2", **change}
    with pytest.raises(ValueError):
        compute_average_daily_balance(
            [row],
            opening_balance=Decimal(0),
            currency="EUR",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"currency": ""},
        {"currency": "UNKNOWN"},
        {"opening_balance": Decimal("NaN")},
        {"period_end": date(2025, 12, 31)},
    ],
)
def test_daily_balance_rejects_invalid_period_metadata(change):
    kwargs = {
        "opening_balance": Decimal(0),
        "currency": "EUR",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
    }
    with pytest.raises(ValueError):
        compute_average_daily_balance([], **{**kwargs, **change})


def test_run_rate_counts_quiet_months_and_keeps_currencies_separate():
    rows = [
        {"date": "2025-12-01", "amount": "-30.123", "currency": "KWD"},
        {"date": "2026-02-28", "amount": "-30.123", "currency": "KWD"},
        {"date": "2026-02-01", "amount": "10", "currency": "EUR"},
    ]
    metrics = compute_cash_flow_summary(rows)
    assert metrics["KWD"].burn_rate_monthly == Decimal("20.082")
    assert metrics["KWD"].projected_annual_run_rate == Decimal("-240.984")
    assert metrics["EUR"].projected_annual_run_rate == 120
    assert metrics["KWD"].to_dict()["burn_rate_monthly"] == "20.082"


def test_explicit_partial_periods_use_calendar_month_lengths():
    row = {"date": "2024-02-29", "amount": "-29", "currency": "EUR"}
    metrics = compute_cash_flow_summary(
        [row], period_start=date(2024, 2, 29), period_end=date(2024, 2, 29)
    )["EUR"]
    assert metrics.burn_rate_monthly == Decimal(29) / (Decimal(1) / 29)
    assert metrics.projected_annual_run_rate == -metrics.burn_rate_monthly * 12
    assert (
        compute_cash_flow_summary(
            [], period_start=date(2024, 2, 1), period_end=date(2024, 2, 29)
        )
        == {}
    )


def test_unknown_dates_disable_extrapolation_but_preserve_totals():
    result = compute_cash_flow_summary(
        [{"amount": "-1"}, {"amount": "2", "date": "2026-01-01"}]
    )["UNKNOWN"]
    assert result.net_cash_flow == 1
    assert result.burn_rate_monthly is None
    assert result.projected_annual_run_rate is None
    assert result.to_dict()["projected_annual_run_rate"] is None
    assert result.to_dict()["burn_rate_monthly"] is None


@pytest.mark.parametrize(
    "start,end,booked",
    [
        (date(2026, 1, 1), None, "2026-01-01"),
        (None, date(2026, 1, 31), "2026-01-01"),
        (date(2026, 2, 1), date(2026, 1, 31), "2026-01-01"),
        (date(2026, 1, 1), date(2026, 1, 31), "2026-02-01"),
        (date(2026, 1, 1), date(2026, 1, 31), None),
    ],
)
def test_explicit_projection_period_requires_complete_dates(
    start, end, booked
):
    with pytest.raises(ValueError):
        compute_cash_flow_summary(
            [{"date": booked, "amount": "2"}],
            period_start=start,
            period_end=end,
        )


@pytest.mark.parametrize(
    "dates,expected",
    [
        (["2024-01-31", "2024-02-29", "2024-04-30"], "MONTHLY"),
        (["2026-01-01", "2026-01-02", "2026-01-29"], "IRREGULAR"),
        (["2026-01-01", "2026-01-31"], "MONTHLY"),
        (["2026-01-01", "2026-02-02"], "MONTHLY"),
        (["2026-01-01", "2026-02-01", "2026-06-01"], "IRREGULAR"),
    ],
)
def test_recurrence_uses_calendar_and_consistent_intervals(dates, expected):
    from bankstatementparser import detect_recurring_transactions

    pattern = detect_recurring_transactions(
        [
            {
                "date": d,
                "amount": "-10",
                "currency": "EUR",
                "description": "Rent",
            }
            for d in dates
        ]
    )[0]
    assert pattern.cadence.value == expected
