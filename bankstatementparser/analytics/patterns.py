# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Recurring cadence detection and anomaly identification engine."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import Any

from .cash_flow import compute_cash_flow_summary
from .common import (
    _amount_and_direction,
    _extract_amount,
    _extract_date,
    _get_attr,
)
from .models import (
    AnalyticsReport,
    AnomalyFinding,
    RecurringCadence,
    RecurringPattern,
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


def _cluster_transaction(
    tx: Any,
    clusters: dict[
        tuple[str | None, str, str, Decimal], list[tuple[date, str]]
    ],
) -> None:
    """Extract attributes from a transaction and record into matching cluster."""
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
    norm_desc = " ".join(desc.split())
    curr = str(_get_attr(tx, "currency", default="UNKNOWN")).upper()
    raw_amount, is_credit = _amount_and_direction(tx)
    amt = abs(raw_amount) if is_credit else -abs(raw_amount)
    if amt == 0:
        return
    account = _get_attr(tx, "account_id", default=None)
    account_id = str(account) if account is not None else None
    d = _extract_date(
        _get_attr(tx, "booking_date", "value_date", "date", default=None)
    )
    h = str(_get_attr(tx, "transaction_hash", "hash", default=""))
    if d is not None:
        clusters[(account_id, norm_desc, curr, amt)].append((d, h))


def _is_calendar_monthly(distinct_dates: list[date]) -> bool:
    """Check if distinct dates follow a calendar-aligned monthly cadence."""
    month_steps = [
        (right.year - left.year) * 12 + right.month - left.month
        for left, right in pairwise(distinct_dates)
    ]
    anchor = max(d.day for d in distinct_dates)
    return (
        min(month_steps) == 1
        and max(month_steps) <= 3
        and all(
            d.day == min(anchor, monthrange(d.year, d.month)[1])
            for d in distinct_dates
        )
    )


def _evaluate_cadence(
    intervals: list[int],
    distinct_dates: list[date],
) -> tuple[RecurringCadence, float]:
    """Estimate recurring cadence and confidence from interval distribution."""
    if _is_calendar_monthly(distinct_dates):
        return RecurringCadence.MONTHLY, 0.95
    shortest, longest = min(intervals), max(intervals)
    if 0 <= shortest <= longest <= 2:
        return RecurringCadence.DAILY, 0.90
    if 5 <= shortest <= longest <= 9:
        return RecurringCadence.WEEKLY, 0.95
    if 12 <= shortest <= longest <= 16:
        return RecurringCadence.BI_WEEKLY, 0.92
    if 26 <= shortest <= longest <= 35:
        return RecurringCadence.MONTHLY, 0.95
    if 80 <= shortest <= longest <= 100:
        return RecurringCadence.QUARTERLY, 0.90
    if 350 <= shortest <= longest <= 380:
        return RecurringCadence.ANNUAL, 0.90
    return RecurringCadence.IRREGULAR, 0.60


def _build_cluster_pattern(
    account_id: str | None,
    desc: str,
    curr: str,
    amt: Decimal,
    dates_and_hashes: list[tuple[date, str]],
    min_occurrences: int,
) -> RecurringPattern | None:
    """Evaluate cluster dates and return a RecurringPattern if threshold met."""
    if len(dates_and_hashes) < min_occurrences:
        return None
    sorted_entries = sorted(dates_and_hashes, key=lambda x: x[0])
    dates = [x[0] for x in sorted_entries]
    distinct_dates = sorted(set(dates))
    if len(distinct_dates) < min_occurrences:
        return None
    intervals = [
        (distinct_dates[i + 1] - distinct_dates[i]).days
        for i in range(len(distinct_dates) - 1)
    ]
    cadence, conf = _evaluate_cadence(intervals, distinct_dates)
    hashes = [x[1] for x in sorted_entries if x[1]]
    return RecurringPattern(
        description=desc,
        amount=abs(amt),
        currency=curr,
        account_id=account_id,
        is_income=amt > 0,
        cadence=cadence,
        confidence=conf,
        occurrence_count=len(dates),
        transaction_dates=[d.isoformat() for d in dates],
        sample_hashes=hashes[:5],
    )


def detect_recurring_transactions(
    transactions: Iterable[Any],
    min_occurrences: int = 2,
) -> list[RecurringPattern]:
    """Detect recurring salaries, utility payments, and subscriptions."""
    if min_occurrences < 2:
        raise ValueError("min_occurrences must be at least 2")
    clusters: dict[
        tuple[str | None, str, str, Decimal], list[tuple[date, str]]
    ] = defaultdict(list)

    for tx in transactions:
        _cluster_transaction(tx, clusters)

    patterns: list[RecurringPattern] = []
    for (account_id, desc, curr, amt), dates_and_hashes in clusters.items():
        pattern = _build_cluster_pattern(
            account_id, desc, curr, amt, dates_and_hashes, min_occurrences
        )
        if pattern is not None:
            patterns.append(pattern)

    return sorted(
        patterns,
        key=lambda p: (p.confidence, p.occurrence_count),
        reverse=True,
    )


def _check_nsf_keywords(
    desc: str,
    amt: Decimal,
    curr: Any,
    b_date: Any,
    h: Any,
) -> AnomalyFinding | None:
    """Check if transaction description matches NSF or overdraft keywords."""
    for kw in _NSF_KEYWORDS:
        if kw in desc:
            return AnomalyFinding(
                finding_type="NSF_OVERDRAFT_FEE",
                severity="HIGH",
                description=f"Identified fee or returned item matching pattern '{kw}': {desc}",
                amount=amt,
                currency=str(curr) if curr else None,
                booking_date=str(b_date) if b_date else None,
                transaction_hash=str(h) if h else None,
            )
    return None


def _detect_statistical_outliers(
    tx_list: list[Any],
    amounts: list[Decimal],
) -> list[AnomalyFinding]:
    """Detect transactions exceeding 4x median volume as statistical outliers."""
    if len(amounts) < 10:
        return []
    sorted_amts = sorted(amounts)
    mid = len(sorted_amts) // 2
    median = sorted_amts[mid]
    threshold = max(Decimal("100.00"), median * 4)

    findings: list[AnomalyFinding] = []
    for tx in tx_list:
        amt = abs(
            _extract_amount(_get_attr(tx, "amount", "amt", default=None))
        )
        if amt > threshold:
            desc = str(
                _get_attr(tx, "description", "narrative", default="High Value")
            )
            curr = _get_attr(tx, "currency", "curr", default=None)
            b_date = _get_attr(tx, "booking_date", "value_date", default=None)
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


def detect_anomalies_and_nsf(
    transactions: Iterable[Any],
) -> list[AnomalyFinding]:
    """Detect NSF fees, overdraft charges, returned items, and statistical outliers."""
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

        nsf_finding = _check_nsf_keywords(desc, amt, curr, b_date, h)
        if nsf_finding is not None:
            findings.append(nsf_finding)

        if amt != Decimal("0.00"):
            amounts.append(abs(amt))

    findings.extend(_detect_statistical_outliers(tx_list, amounts))
    return findings


def analyze_statement_transactions(
    transactions: Iterable[Any],
) -> AnalyticsReport:
    """Generate comprehensive analytics report covering spreads, cadence, and anomalies."""
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
