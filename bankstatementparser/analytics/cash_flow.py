# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Cash-flow spreading and average daily balance computation."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from .._amounts import iso_decimal
from .common import (
    _amount_and_direction,
    _calendar_months,
    _extract_date,
    _get_attr,
)
from .models import CashFlowMetrics, DailyBalanceMetrics


def _process_daily_balance_tx(
    tx: Any,
    currency: str,
    account_id: str | None,
    period_start: date,
    period_end: date,
) -> tuple[Decimal, int]:
    """Validate transaction account/currency/date and return signed amount with days remaining."""
    tx_currency = str(_get_attr(tx, "currency", default="UNKNOWN")).upper()
    raw_account = _get_attr(tx, "account_id", default=None)
    tx_account = str(raw_account) if raw_account is not None else None
    if tx_currency != currency or tx_account != account_id:
        raise ValueError("Daily balance requires one account and currency")
    booked = _extract_date(_get_attr(tx, "booking_date", "date"))
    if booked is None or not period_start <= booked <= period_end:
        raise ValueError("Every booking date must fall within the period")
    amount, credit = _amount_and_direction(tx)
    signed = abs(amount) if credit else -abs(amount)
    days_remaining = (period_end - booked).days + 1
    return signed, days_remaining


def compute_average_daily_balance(
    transactions: Iterable[Any],
    *,
    opening_balance: Decimal,
    period_start: date,
    period_end: date,
    currency: str,
    account_id: str | None = None,
) -> DailyBalanceMetrics:
    """Average end-of-day balances, including days without transactions.

    Opening balance is the balance immediately before the first day. Each
    booking affects that day's closing balance through the inclusive end date.
    The caller must supply the complete period and all its posted transactions.
    Reject mixed accounts/currencies, missing dates and out-of-period rows;
    never infer an opening balance from incomplete transaction history.
    Runtime is linear in rows, without allocating one balance per day.
    """
    if period_end < period_start:
        raise ValueError("period_end must not precede period_start")
    clean_currency = currency.strip().upper()
    if not clean_currency or clean_currency == "UNKNOWN":
        raise ValueError("An explicit currency is required")
    opening = iso_decimal(str(opening_balance), context="opening balance")
    days = (period_end - period_start).days + 1
    weighted_balance = opening * days
    closing = opening
    for tx in transactions:
        signed, days_remaining = _process_daily_balance_tx(
            tx, clean_currency, account_id, period_start, period_end
        )
        closing += signed
        weighted_balance += signed * days_remaining
    return DailyBalanceMetrics(
        account_id,
        clean_currency,
        period_start,
        period_end,
        opening,
        closing,
        weighted_balance / days,
        days,
    )


def _validate_period(
    period_start: date | None, period_end: date | None
) -> None:
    """Validate consistency of start and end period parameters."""
    if (period_start is None) != (period_end is None):
        raise ValueError("Supply both period_start and period_end")
    if (
        period_start is not None
        and period_end is not None
        and period_end < period_start
    ):
        raise ValueError("period_end must not precede period_start")


def _calculate_run_rates(
    dates: list[date],
    tx_count: int,
    total_outflow: Decimal,
    net_cash: Decimal,
    period_start: date | None,
    period_end: date | None,
) -> tuple[Decimal | None, Decimal | None]:
    """Calculate monthly burn rate and annual run rate if all dates are present."""
    if len(dates) != tx_count:
        return None, None
    first, last = min(dates), max(dates)
    start = period_start or first.replace(day=1)
    end = period_end or last.replace(day=monthrange(last.year, last.month)[1])
    months = _calendar_months(start, end)
    burn_rate = total_outflow / months
    projected_run_rate = net_cash / months * 12
    return burn_rate, projected_run_rate


class _CurrencyAccumulator:
    """Accumulates cash flow figures and metrics for a single currency."""

    def __init__(
        self,
        curr: str,
        period_start: date | None,
        period_end: date | None,
    ) -> None:
        """Initialize currency accumulator state."""
        self.curr = curr
        self.period_start = period_start
        self.period_end = period_end
        self.total_inflow = Decimal("0.00")
        self.total_outflow = Decimal("0.00")
        self.credit_count = 0
        self.debit_count = 0
        self.dates: list[date] = []
        self.monthly_inflows: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0.00")
        )
        self.monthly_outflows: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0.00")
        )

    def process_tx(self, tx: Any) -> None:
        """Process a single transaction into currency aggregates."""
        amt, is_credit = _amount_and_direction(tx)
        abs_amt = abs(amt)
        d = _extract_date(
            _get_attr(tx, "booking_date", "value_date", "date", default=None)
        )
        m_key = d.strftime("%Y-%m") if d else "UNKNOWN"
        if (
            self.period_start is not None
            and self.period_end is not None
            and (d is None or not self.period_start <= d <= self.period_end)
        ):
            raise ValueError("Every booking date must fall within the period")
        if d is not None:
            self.dates.append(d)

        if is_credit:
            self.total_inflow += abs_amt
            self.credit_count += 1
            self.monthly_inflows[m_key] += abs_amt
        else:
            self.total_outflow += abs_amt
            self.debit_count += 1
            self.monthly_outflows[m_key] += abs_amt

    def build_metrics(self, tx_count: int) -> CashFlowMetrics:
        """Build finalized CashFlowMetrics from accumulated totals."""
        net_cash = self.total_inflow - self.total_outflow
        avg_in = (
            self.total_inflow / Decimal(self.credit_count)
            if self.credit_count > 0
            else Decimal("0.00")
        )
        avg_out = (
            self.total_outflow / Decimal(self.debit_count)
            if self.debit_count > 0
            else Decimal("0.00")
        )
        avg_amt = (
            (self.total_inflow + self.total_outflow) / Decimal(tx_count)
            if tx_count > 0
            else Decimal("0.00")
        )

        burn_rate, projected_run_rate = _calculate_run_rates(
            self.dates,
            tx_count,
            self.total_outflow,
            net_cash,
            self.period_start,
            self.period_end,
        )

        return CashFlowMetrics(
            currency=self.curr,
            total_inflow=self.total_inflow,
            total_outflow=self.total_outflow,
            net_cash_flow=net_cash,
            transaction_count=tx_count,
            credit_count=self.credit_count,
            debit_count=self.debit_count,
            average_inflow=avg_in,
            average_outflow=avg_out,
            average_transaction_amount=avg_amt,
            monthly_inflows={
                k: str(v) for k, v in self.monthly_inflows.items()
            },
            monthly_outflows={
                k: str(v) for k, v in self.monthly_outflows.items()
            },
            burn_rate_monthly=burn_rate,
            projected_annual_run_rate=projected_run_rate,
        )


def compute_cash_flow_summary(
    transactions: Iterable[Any],
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, CashFlowMetrics]:
    """Calculate cash flow spreads, volume, and run rates grouped by currency."""
    _validate_period(period_start, period_end)
    groups: dict[str, list[Any]] = defaultdict(list)
    for tx in transactions:
        curr = _get_attr(tx, "currency", "curr", default="UNKNOWN")
        groups[str(curr).upper()].append(tx)

    results: dict[str, CashFlowMetrics] = {}
    for curr, txs in groups.items():
        accumulator = _CurrencyAccumulator(curr, period_start, period_end)
        for tx in txs:
            accumulator.process_tx(tx)
        results[curr] = accumulator.build_metrics(len(txs))

    return results
