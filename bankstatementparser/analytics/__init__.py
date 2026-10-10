# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Treasury Cash-Flow Spreading, Cadence Detection, and Anomaly Engine."""

from __future__ import annotations

from .cash_flow import (
    compute_average_daily_balance,
    compute_cash_flow_summary,
)
from .common import (
    _amount_and_direction,
    _calendar_months,
    _extract_amount,
    _extract_date,
    _get_attr,
)
from .models import (
    AnalyticsReport,
    AnomalyFinding,
    CashFlowMetrics,
    DailyBalanceMetrics,
    RecurringCadence,
    RecurringPattern,
)
from .patterns import (
    analyze_statement_transactions,
    detect_anomalies_and_nsf,
    detect_recurring_transactions,
)

__all__ = [
    "AnalyticsReport",
    "AnomalyFinding",
    "CashFlowMetrics",
    "DailyBalanceMetrics",
    "RecurringCadence",
    "RecurringPattern",
    "_amount_and_direction",
    "_calendar_months",
    "_extract_amount",
    "_extract_date",
    "_get_attr",
    "analyze_statement_transactions",
    "compute_average_daily_balance",
    "compute_cash_flow_summary",
    "detect_anomalies_and_nsf",
    "detect_recurring_transactions",
]
