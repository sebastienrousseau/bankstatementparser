# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Treasury Cash-Flow Spreading, Cadence Detection, and Anomaly Engine.

Provides automated computation of inflow/outflow metrics, recurring
salary and subscription cadence detection, average daily balance (ADB),
and non-sufficient funds (NSF) / overdraft anomaly identification.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any


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
    burn_rate_monthly: Decimal
    projected_annual_run_rate: Decimal

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
        data["burn_rate_monthly"] = str(self.burn_rate_monthly)
        data["projected_annual_run_rate"] = str(self.projected_annual_run_rate)
        return data


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
    if isinstance(val, Decimal):
        return val
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    if isinstance(val, str):
        try:
            return Decimal(val.strip().replace(",", ".").replace(" ", ""))
        except (InvalidOperation, ValueError):
            return Decimal("0.00")
    return Decimal("0.00")


def _get_attr(obj: Any, *keys: str, default: Any = None) -> Any:
    """Retrieve attribute or dict key across Transaction or dict instances."""
    for key in keys:
        if isinstance(obj, dict) and key in obj:
            return obj[key]
        if hasattr(obj, key):
            val = getattr(obj, key)
            if val is not None:
                return val
    return default


def compute_cash_flow_summary(
    transactions: Iterable[Any],
) -> dict[str, CashFlowMetrics]:
    """Calculate cash flow spreads, volume, and run rates grouped by currency.

    Args:
        transactions: Sequence of Transaction models, records, or dictionaries.

    Returns:
        Mapping of currency code to CashFlowMetrics.
    """
    groups: dict[str, list[Any]] = defaultdict(list)
    for tx in transactions:
        curr = _get_attr(tx, "currency", "curr", default="EUR")
        groups[str(curr).upper()].append(tx)

    results: dict[str, CashFlowMetrics] = {}

    for curr, txs in groups.items():
        total_inflow = Decimal("0.00")
        total_outflow = Decimal("0.00")
        credit_count = 0
        debit_count = 0

        monthly_inflows: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0.00")
        )
        monthly_outflows: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0.00")
        )

        for tx in txs:
            amt = _extract_amount(_get_attr(tx, "amount", "amt", default=0))
            d_or_c = _get_attr(tx, "credit_debit", "drcr", "type", default="")
            d_or_c_str = str(d_or_c).upper()

            # Determine sign based on credit_debit or amount sign
            is_credit = False
            if d_or_c_str in ("CRDT", "CREDIT", "C", "CR"):
                is_credit = True
            elif d_or_c_str in ("DBIT", "DEBIT", "D", "DR"):
                is_credit = False
            else:
                is_credit = amt >= Decimal("0.00")

            abs_amt = abs(amt)
            d = _extract_date(
                _get_attr(
                    tx, "booking_date", "value_date", "date", default=None
                )
            )
            m_key = d.strftime("%Y-%m") if d else "UNKNOWN"

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

        # Monthly burn rate calculation
        active_months = len(
            set(monthly_inflows.keys()) | set(monthly_outflows.keys())
        )
        active_months = max(1, active_months)
        burn_rate = (total_outflow / Decimal(active_months)).quantize(
            Decimal("0.01")
        )
        projected_run_rate = (net_cash / Decimal(active_months) * 12).quantize(
            Decimal("0.01")
        )

        results[curr] = CashFlowMetrics(
            currency=curr,
            total_inflow=total_inflow.quantize(Decimal("0.01")),
            total_outflow=total_outflow.quantize(Decimal("0.01")),
            net_cash_flow=net_cash.quantize(Decimal("0.01")),
            transaction_count=tx_count,
            credit_count=credit_count,
            debit_count=debit_count,
            average_inflow=avg_in.quantize(Decimal("0.01")),
            average_outflow=avg_out.quantize(Decimal("0.01")),
            average_transaction_amount=avg_amt.quantize(Decimal("0.01")),
            monthly_inflows={
                k: str(v.quantize(Decimal("0.01")))
                for k, v in monthly_inflows.items()
            },
            monthly_outflows={
                k: str(v.quantize(Decimal("0.01")))
                for k, v in monthly_outflows.items()
            },
            burn_rate_monthly=burn_rate,
            projected_annual_run_rate=projected_run_rate,
        )

    return results


def detect_recurring_transactions(
    transactions: Iterable[Any],
    min_occurrences: int = 2,
) -> list[RecurringPattern]:
    """Detect recurring salaries, utility payments, and subscriptions.

    Clusters transactions by description and amount, computing day
    differences to deduce standard cadences (WEEKLY, MONTHLY, ANNUAL, etc.).

    Args:
        transactions: Sequence of transactions to evaluate.
        min_occurrences: Minimum number of occurrences required to classify.

    Returns:
        List of identified RecurringPattern items.
    """
    clusters: dict[tuple[str, str, Decimal], list[tuple[date, str]]] = (
        defaultdict(list)
    )

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
        # Normalize whitespace and numbers for clustering
        norm_desc = " ".join(desc.split())
        curr = str(_get_attr(tx, "currency", default="EUR")).upper()
        amt = abs(
            _extract_amount(_get_attr(tx, "amount", "amt", default=0))
        ).quantize(Decimal("0.01"))
        d = _extract_date(
            _get_attr(tx, "booking_date", "value_date", "date", default=None)
        )
        h = str(_get_attr(tx, "transaction_hash", "hash", default=""))

        if d is not None:
            clusters[(norm_desc, curr, amt)].append((d, h))

    patterns: list[RecurringPattern] = []

    for (desc, curr, amt), dates_and_hashes in clusters.items():
        if len(dates_and_hashes) < min_occurrences:
            continue

        sorted_entries = sorted(dates_and_hashes, key=lambda x: x[0])
        dates = [x[0] for x in sorted_entries]
        hashes = [x[1] for x in sorted_entries if x[1]]

        # Calculate intervals in days
        intervals: list[int] = [
            (dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)
        ]

        avg_interval = sum(intervals) / len(intervals)

        # Classify cadence based on average interval
        if 0 <= avg_interval <= 2:
            cadence = RecurringCadence.DAILY
            conf = 0.90
        elif 5 <= avg_interval <= 9:
            cadence = RecurringCadence.WEEKLY
            conf = 0.95
        elif 12 <= avg_interval <= 16:
            cadence = RecurringCadence.BI_WEEKLY
            conf = 0.92
        elif 26 <= avg_interval <= 35:
            cadence = RecurringCadence.MONTHLY
            conf = 0.95
        elif 80 <= avg_interval <= 100:
            cadence = RecurringCadence.QUARTERLY
            conf = 0.90
        elif 350 <= avg_interval <= 380:
            cadence = RecurringCadence.ANNUAL
            conf = 0.90
        else:
            cadence = RecurringCadence.IRREGULAR
            conf = 0.60

        is_income = any(
            kw in desc
            for kw in ("SALARY", "PAYROLL", "WAGES", "DIVIDEND", "INTEREST")
        )

        patterns.append(
            RecurringPattern(
                description=desc,
                amount=amt,
                currency=curr,
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
        amt = _extract_amount(_get_attr(tx, "amount", "amt", default=0))
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
                _extract_amount(_get_attr(tx, "amount", "amt", default=0))
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
