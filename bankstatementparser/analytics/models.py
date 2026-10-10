# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Data models for treasury analytics, cash flow, and anomaly detection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
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
