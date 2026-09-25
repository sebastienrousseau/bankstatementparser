# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Treasury Cash-Flow Spreading, Cadence Detection, and Anomaly Engine.

Provides automated computation of inflow/outflow metrics, recurring
salary and subscription cadence detection, average daily balance (ADB),
and non-sufficient funds (NSF) / overdraft anomaly identification.
"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from itertools import pairwise
from typing import Any

from ._amounts import iso_decimal


class RecurringCadence(str, Enum):
    """Estimated repetition cadence for recurring transactions."""

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BI_WEEKLY = "BI_WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"
    IRREGULAR = "IRREGULAR"


@dataclass(frozen=True)
class CashFlowMetrics:
    """Cash flow spread metrics for a single currency or statement set."""

    currency: str
    total_inflow: Decimal
    total_outflow: Decimal
    net_cash_flow: Decimal
    transaction_count: int
    credit_count: int
    debit_count: int
    average_inflow: Decimal
    average_outflow: Decimal
    average_transaction_amount: Decimal
    monthly_inflows: dict[str, str]
    monthly_outflows: dict[str, str]
    burn_rate_monthly: Decimal | None
    projected_annual_run_rate: Decimal | None

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to a clean serializable dictionary."""
        data = asdict(self)
        data["total_inflow"] = str(self.total_inflow)
        data["total_outflow"] = str(self.total_outflow)
        data["net_cash_flow"] = str(self.net_cash_flow)
        data["average_inflow"] = str(self.average_inflow)
        data["average_outflow"] = str(self.average_outflow)
        data["average_transaction_amount"] = str(
            self.average_transaction_amount
        )
        data["burn_rate_monthly"] = (
            str(self.burn_rate_monthly)
            if self.burn_rate_monthly is not None
            else None
        )
        data["projected_annual_run_rate"] = (
            str(self.projected_annual_run_rate)
            if self.projected_annual_run_rate is not None
            else None
        )
        return data


@dataclass(frozen=True)
class DailyBalanceMetrics:
    """End-of-day balance average for one explicitly scoped inclusive period."""

    account_id: str | None
    currency: str
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    average_daily_balance: Decimal
    day_count: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize dates and exact monetary values without float conversion."""
        return {
            key: str(value) if isinstance(value, (date, Decimal)) else value
            for key, value in asdict(self).items()
        }


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
    currency = currency.strip().upper()
    if not currency or currency == "UNKNOWN":
        raise ValueError("An explicit currency is required")
    opening = iso_decimal(str(opening_balance), context="opening balance")
    days = (period_end - period_start).days + 1
    weighted_balance = opening * days
    closing = opening
    for tx in transactions:
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
        closing += signed
        weighted_balance += signed * ((period_end - booked).days + 1)
    return DailyBalanceMetrics(
        account_id,
        currency,
        period_start,
        period_end,
        opening,
        closing,
        weighted_balance / days,
        days,
    )


def _calendar_months(start: date, end: date) -> Decimal:
    """Measure an inclusive period in calendar months, prorating edge months."""
    cursor = start
    months = Decimal(0)
    while True:
        last = date(
            cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1]
        )
        stop = min(last, end)
        months += Decimal((stop - cursor).days + 1) / last.day
        if stop == end:
            return months
        cursor = date(
            cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1
        )


@dataclass(frozen=True)
class RecurringPattern:
    """Detected recurring transaction pattern (e.g. payroll, subscription)."""

    description: str
    amount: Decimal
    currency: str
    is_income: bool
    cadence: RecurringCadence
    confidence: float
    occurrence_count: int
    transaction_dates: list[str]
    sample_hashes: list[str]
    account_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert recurring pattern to dictionary."""
        data = asdict(self)
        data["amount"] = str(self.amount)
        data["cadence"] = self.cadence.value
        return data


@dataclass(frozen=True)
class AnomalyFinding:
    """Detected irregularity, fee spike, or NSF/overdraft transaction."""

    finding_type: str
    severity: str
    description: str
    amount: Decimal | None
    currency: str | None
    booking_date: str | None
    transaction_hash: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert anomaly finding to dictionary."""
        data = asdict(self)
        if self.amount is not None:
            data["amount"] = str(self.amount)
        return {k: v for k, v in data.items() if v is not None}


@dataclass(frozen=True)
class AnalyticsReport:
    """Comprehensive analytical summary for a batch of transactions."""

    summary_by_currency: dict[str, CashFlowMetrics]
    recurring_patterns: list[RecurringPattern]
    anomalies: list[AnomalyFinding]
    total_transactions_analyzed: int

    def to_dict(self) -> dict[str, Any]:
        """Convert complete report to serializable dictionary."""
        return {
            "summary_by_currency": {
                curr: m.to_dict()
                for curr, m in self.summary_by_currency.items()
            },
            "recurring_patterns": [
                p.to_dict() for p in self.recurring_patterns
            ],
            "anomalies": [a.to_dict() for a in self.anomalies],
            "total_transactions_analyzed": self.total_transactions_analyzed,
        }


def _extract_date(val: Any) -> date | None:
    """Parse arbitrary date object or string into a datetime.date."""
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        val_clean = val.strip()[:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(val_clean, fmt).date()
            except ValueError:
                continue
    return None


def _extract_amount(val: Any) -> Decimal:
    """Convert amount attribute to Decimal."""
    return iso_decimal(
        str(val).strip().replace(",", ".").replace(" ", ""),
        context="analytics amount",
    )


def _get_attr(obj: Any, *keys: str, default: Any = None) -> Any:
    """Retrieve attribute or dict key across Transaction or dict instances."""
    aliases = {
        "amount": ("Amount", "InstdAmt"),
        "currency": ("Currency",),
        "booking_date": ("BookgDt",),
        "value_date": ("ValDt",),
        "description": ("Description", "Reference", "RmtInf"),
        "credit_debit": ("DrCr",),
        "account_id": ("AccountId", "DbtrIBAN"),
    }
    expanded = [
        alias for key in keys for alias in (key, *aliases.get(key, ()))
    ]
    for key in expanded:
        if isinstance(obj, dict) and key in obj and obj[key] not in (None, ""):
            return obj[key]
        if hasattr(obj, key):
            val = getattr(obj, key)
            if val is not None:
                return val
    return default


def _amount_and_direction(tx: Any) -> tuple[Decimal, bool]:
    """Resolve explicit bank direction before falling back to amount sign."""
    amount = _extract_amount(_get_attr(tx, "amount", "amt", default=None))
    direction = str(
        _get_attr(tx, "credit_debit", "drcr", "type", default="")
    ).upper()
    if direction in ("CRDT", "CREDIT", "C", "CR"):
        return amount, True
    if direction in ("DBIT", "DEBIT", "D", "DR"):
        return amount, False
    return amount, amount >= 0


def compute_cash_flow_summary(
    transactions: Iterable[Any],
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict[str, CashFlowMetrics]:
    """Calculate cash flow spreads, volume, and run rates grouped by currency.

    Args:
        transactions: Sequence of Transaction models, records, or dictionaries.
        period_start: Inclusive reporting-period start, paired with period_end.
        period_end: Inclusive reporting-period end. Explicit periods prorate
            partial calendar months and reject undated/outside transactions.
            Without a period, assume complete calendar months between the
            earliest and latest booking, including quiet months. Any undated
            row makes run rates unavailable. Rates are historical extrapolations.

    Returns:
        Mapping of currency code to CashFlowMetrics.
    """
    if (period_start is None) != (period_end is None):
        raise ValueError("Supply both period_start and period_end")
    if (
        period_start is not None
        and period_end is not None
        and period_end < period_start
    ):
        raise ValueError("period_end must not precede period_start")
    groups: dict[str, list[Any]] = defaultdict(list)
    for tx in transactions:
        curr = _get_attr(tx, "currency", "curr", default="UNKNOWN")
        groups[str(curr).upper()].append(tx)

    results: dict[str, CashFlowMetrics] = {}

    for curr, txs in groups.items():
        total_inflow = Decimal("0.00")
        total_outflow = Decimal("0.00")
        credit_count = 0
        debit_count = 0
        dates: list[date] = []

        monthly_inflows: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0.00")
        )
        monthly_outflows: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0.00")
        )

        for tx in txs:
            # Determine sign based on credit_debit or amount sign.
            amt, is_credit = _amount_and_direction(tx)

            abs_amt = abs(amt)
            d = _extract_date(
                _get_attr(
                    tx, "booking_date", "value_date", "date", default=None
                )
            )
            m_key = d.strftime("%Y-%m") if d else "UNKNOWN"
            if (
                period_start is not None
                and period_end is not None
                and (d is None or not period_start <= d <= period_end)
            ):
                raise ValueError(
                    "Every booking date must fall within the period"
                )
            if d is not None:
                dates.append(d)

            if is_credit:
                total_inflow += abs_amt
                credit_count += 1
                monthly_inflows[m_key] += abs_amt
            else:
                total_outflow += abs_amt
                debit_count += 1
                monthly_outflows[m_key] += abs_amt

        tx_count = len(txs)
        net_cash = total_inflow - total_outflow
        avg_in = (
            total_inflow / Decimal(credit_count)
            if credit_count > 0
            else Decimal("0.00")
        )
        avg_out = (
            total_outflow / Decimal(debit_count)
            if debit_count > 0
            else Decimal("0.00")
        )
        avg_amt = (
            (total_inflow + total_outflow) / Decimal(tx_count)
            if tx_count > 0
            else Decimal("0.00")
        )

        # Monthly burn rate includes quiet calendar months. Undated rows make
        # the observation period unknowable, rather than inventing one month.
        burn_rate = projected_run_rate = None
        if len(dates) == tx_count:
            first, last = min(dates), max(dates)
            start = period_start or first.replace(day=1)
            end = period_end or last.replace(
                day=monthrange(last.year, last.month)[1]
            )
            months = _calendar_months(start, end)
            burn_rate = total_outflow / months
            projected_run_rate = net_cash / months * 12

        results[curr] = CashFlowMetrics(
            currency=curr,
            total_inflow=total_inflow,
            total_outflow=total_outflow,
            net_cash_flow=net_cash,
            transaction_count=tx_count,
            credit_count=credit_count,
            debit_count=debit_count,
            average_inflow=avg_in,
            average_outflow=avg_out,
            average_transaction_amount=avg_amt,
            monthly_inflows={k: str(v) for k, v in monthly_inflows.items()},
            monthly_outflows={k: str(v) for k, v in monthly_outflows.items()},
            burn_rate_monthly=burn_rate,
            projected_annual_run_rate=projected_run_rate,
        )

    return results


def detect_recurring_transactions(
    transactions: Iterable[Any],
    min_occurrences: int = 2,
) -> list[RecurringPattern]:
    """Detect recurring salaries, utility payments, and subscriptions.

    Clusters by account, currency, direction, description and amount.
    Cadence uses distinct booking dates; same-day repetitions remain in
    occurrence counts but do not imply a daily schedule. Unknown accounts
    share a separate bucket and are never merged with known accounts.

    Args:
        transactions: Sequence of transactions to evaluate.
        min_occurrences: Minimum distinct booking dates required (at least 2).

    Returns:
        List of identified RecurringPattern items.
    """
    if min_occurrences < 2:
        raise ValueError("min_occurrences must be at least 2")
    clusters: dict[
        tuple[str | None, str, str, Decimal], list[tuple[date, str]]
    ] = defaultdict(list)

    for tx in transactions:
        desc = (
            str(
                _get_attr(
                    tx,
                    "description",
                    "narrative",
                    "remittance_information",
                    default="Unknown",
                )
            )
            .strip()
            .upper()
        )
        # Normalize whitespace for clustering
        norm_desc = " ".join(desc.split())
        curr = str(_get_attr(tx, "currency", default="UNKNOWN")).upper()
        raw_amount, is_credit = _amount_and_direction(tx)
        amt = abs(raw_amount) if is_credit else -abs(raw_amount)
        if amt == 0:
            continue
        account = _get_attr(tx, "account_id", default=None)
        account_id = str(account) if account is not None else None
        d = _extract_date(
            _get_attr(tx, "booking_date", "value_date", "date", default=None)
        )
        h = str(_get_attr(tx, "transaction_hash", "hash", default=""))

        if d is not None:
            clusters[(account_id, norm_desc, curr, amt)].append((d, h))

    patterns: list[RecurringPattern] = []

    for (account_id, desc, curr, amt), dates_and_hashes in clusters.items():
        if len(dates_and_hashes) < min_occurrences:
            continue

        sorted_entries = sorted(dates_and_hashes, key=lambda x: x[0])
        dates = [x[0] for x in sorted_entries]
        hashes = [x[1] for x in sorted_entries if x[1]]

        # Calculate intervals between distinct dates in days.
        distinct_dates = sorted(set(dates))
        if len(distinct_dates) < min_occurrences:
            continue
        intervals: list[int] = [
            (distinct_dates[i + 1] - distinct_dates[i]).days
            for i in range(len(distinct_dates) - 1)
        ]

        month_steps = [
            (right.year - left.year) * 12 + right.month - left.month
            for left, right in pairwise(distinct_dates)
        ]
        anchor = max(d.day for d in distinct_dates)
        calendar_monthly = (
            min(month_steps) == 1
            and max(month_steps) <= 3
            and all(
                d.day == min(anchor, monthrange(d.year, d.month)[1])
                for d in distinct_dates
            )
        )

        # Calendar-aligned monthly payments tolerate up to two missing months.
        # Otherwise every observed interval must fit the cadence: an average
        # of a one-day gap and a 27-day gap is not evidence of biweekly pay.
        shortest, longest = min(intervals), max(intervals)
        if calendar_monthly:
            cadence = RecurringCadence.MONTHLY
            conf = 0.95
        elif 0 <= shortest <= longest <= 2:
            cadence = RecurringCadence.DAILY
            conf = 0.90
        elif 5 <= shortest <= longest <= 9:
            cadence = RecurringCadence.WEEKLY
            conf = 0.95
        elif 12 <= shortest <= longest <= 16:
            cadence = RecurringCadence.BI_WEEKLY
            conf = 0.92
        elif 26 <= shortest <= longest <= 35:
            cadence = RecurringCadence.MONTHLY
            conf = 0.95
        elif 80 <= shortest <= longest <= 100:
            cadence = RecurringCadence.QUARTERLY
            conf = 0.90
        elif 350 <= shortest <= longest <= 380:
            cadence = RecurringCadence.ANNUAL
            conf = 0.90
        else:
            cadence = RecurringCadence.IRREGULAR
            conf = 0.60

        is_income = amt > 0

        patterns.append(
            RecurringPattern(
                description=desc,
                amount=abs(amt),
                currency=curr,
                account_id=account_id,
                is_income=is_income,
                cadence=cadence,
                confidence=conf,
                occurrence_count=len(dates),
                transaction_dates=[d.isoformat() for d in dates],
                sample_hashes=hashes[:5],
            )
        )

    return sorted(
        patterns,
        key=lambda p: (p.confidence, p.occurrence_count),
        reverse=True,
    )


_NSF_KEYWORDS = (
    "NSF",
    "NON-SUFFICIENT",
    "INSUFFICIENT FUNDS",
    "RETURNED ITEM",
    "OVERDRAFT FEE",
    "UNPAID ITEM",
    "CHARGEBACK",
    "REVERSAL",
)


def detect_anomalies_and_nsf(
    transactions: Iterable[Any],
) -> list[AnomalyFinding]:
    """Detect NSF fees, overdraft charges, returned items, and statistical outliers.

    Args:
        transactions: Sequence of transactions to inspect.

    Returns:
        List of identified AnomalyFinding occurrences.
    """
    findings: list[AnomalyFinding] = []
    amounts: list[Decimal] = []

    tx_list = list(transactions)
    for tx in tx_list:
        desc = str(
            _get_attr(
                tx,
                "description",
                "narrative",
                "remittance_information",
                default="",
            )
        ).upper()
        amt = _extract_amount(_get_attr(tx, "amount", "amt", default=None))
        curr = _get_attr(tx, "currency", "curr", default=None)
        b_date = _get_attr(tx, "booking_date", "value_date", default=None)
        h = _get_attr(tx, "transaction_hash", "hash", default=None)

        # 1. Keyword check for NSF / Overdraft / Returned Items
        for kw in _NSF_KEYWORDS:
            if kw in desc:
                findings.append(
                    AnomalyFinding(
                        finding_type="NSF_OVERDRAFT_FEE",
                        severity="HIGH",
                        description=f"Identified fee or returned item matching pattern '{kw}': {desc}",
                        amount=amt,
                        currency=str(curr) if curr else None,
                        booking_date=str(b_date) if b_date else None,
                        transaction_hash=str(h) if h else None,
                    )
                )
                break

        if amt != Decimal("0.00"):
            amounts.append(abs(amt))

    # 2. Statistical Outlier Detection (Transactions > 4x Median)
    if len(amounts) >= 10:
        sorted_amts = sorted(amounts)
        mid = len(sorted_amts) // 2
        median = sorted_amts[mid]
        threshold = max(Decimal("100.00"), median * 4)

        for tx in tx_list:
            amt = abs(
                _extract_amount(_get_attr(tx, "amount", "amt", default=None))
            )
            if amt > threshold:
                desc = str(
                    _get_attr(
                        tx, "description", "narrative", default="High Value"
                    )
                )
                curr = _get_attr(tx, "currency", "curr", default=None)
                b_date = _get_attr(
                    tx, "booking_date", "value_date", default=None
                )
                h = _get_attr(tx, "transaction_hash", "hash", default=None)

                findings.append(
                    AnomalyFinding(
                        finding_type="STATISTICAL_OUTLIER",
                        severity="MEDIUM",
                        description=f"Transaction volume ({amt}) exceeds 4x median ({median}) for account: {desc}",
                        amount=amt,
                        currency=str(curr) if curr else None,
                        booking_date=str(b_date) if b_date else None,
                        transaction_hash=str(h) if h else None,
                    )
                )

    return findings


def analyze_statement_transactions(
    transactions: Iterable[Any],
) -> AnalyticsReport:
    """Generate comprehensive analytics report covering spreads, cadence, and anomalies.

    Args:
        transactions: Sequence of transactions to evaluate.

    Returns:
        Structured AnalyticsReport object.
    """
    tx_list = list(transactions)
    spreads = compute_cash_flow_summary(tx_list)
    recurring = detect_recurring_transactions(tx_list)
    anomalies = detect_anomalies_and_nsf(tx_list)

    return AnalyticsReport(
        summary_by_currency=spreads,
        recurring_patterns=recurring,
        anomalies=anomalies,
        total_transactions_analyzed=len(tx_list),
    )
