# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Two-Way Payment-to-Statement Cross-Reconciliation Engine.

Cross-references outgoing payment initiation records (PAIN.001, ERP exports)
against incoming settlement statements (CAMT.053, MT940, CSV, BAI2),
computing match confidence, detecting partial amount deductions, and
reporting discrepancy matrices.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from ._amounts import iso_decimal
from .transaction_models import _parse_date


class ReconciliationStatus(str, Enum):
    """Reconciliation match categorization."""

    EXACT_REFERENCE = "EXACT_REFERENCE"
    EXACT_AMOUNT_AND_PARTY = "EXACT_AMOUNT_AND_PARTY"
    FUZZY_MATCH = "FUZZY_MATCH"
    PARTIAL_AMOUNT_DEDUCTION = "PARTIAL_AMOUNT_DEDUCTION"
    UNMATCHED = "UNMATCHED"


@dataclass(frozen=True)
class ReconciliationMatch:
    """A matched pair linking a payment instruction to a statement transaction."""

    status: ReconciliationStatus
    confidence: float
    payment_record: dict[str, Any]
    statement_record: dict[str, Any]
    amount_difference: Decimal
    matched_on: str

    def to_dict(self) -> dict[str, Any]:
        """Convert match pair to clean dictionary."""
        data = asdict(self)
        data["status"] = self.status.value
        data["amount_difference"] = str(self.amount_difference)
        return data


@dataclass(frozen=True)
class ReconciliationReport:
    """Comprehensive reconciliation report comparing payments against statements."""

    total_payments: int
    total_statements: int
    matched_count: int
    unmatched_payment_count: int
    unmatched_statement_count: int
    partial_deduction_count: int
    match_rate: float
    total_reconciled_volume: Decimal | None
    matches: list[ReconciliationMatch]
    unmatched_payments: list[dict[str, Any]]
    unmatched_statements: list[dict[str, Any]]
    reconciled_volume_by_currency: dict[str, Decimal] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert report to serializable dictionary."""
        return {
            "total_payments": self.total_payments,
            "total_statements": self.total_statements,
            "matched_count": self.matched_count,
            "unmatched_payment_count": self.unmatched_payment_count,
            "unmatched_statement_count": self.unmatched_statement_count,
            "partial_deduction_count": self.partial_deduction_count,
            "match_rate": self.match_rate,
            "total_reconciled_volume": (
                str(self.total_reconciled_volume)
                if self.total_reconciled_volume is not None
                else None
            ),
            "reconciled_volume_by_currency": {
                currency: str(amount)
                for currency, amount in self.reconciled_volume_by_currency.items()
            },
            "matches": [m.to_dict() for m in self.matches],
            "unmatched_payments": self.unmatched_payments,
            "unmatched_statements": self.unmatched_statements,
        }


def _to_record_dict(item: Any) -> dict[str, Any]:
    """Convert an input item (DataFrame row, dict, model) to a dict."""
    if isinstance(item, dict):
        return cast(dict[str, Any], item)
    if hasattr(item, "model_dump"):
        return cast(dict[str, Any], item.model_dump())
    if hasattr(item, "to_dict"):
        return cast(dict[str, Any], item.to_dict())
    if hasattr(item, "__dict__") and bool(item.__dict__):
        return {
            k: v for k, v in item.__dict__.items() if not k.startswith("_")
        }
    return {"raw": str(item)}


def _extract_amount(val: Any) -> Decimal:
    """Convert value to Decimal."""
    return iso_decimal(
        str(val).strip().replace(",", "."), context="reconciliation amount"
    )


def _get_val(d: dict[str, Any], *keys: str) -> str:
    """Retrieve string value for first matching key in dictionary."""
    for k in keys:
        if k in d and d[k] is not None:
            return str(d[k]).strip()
    return ""


def reconcile_payments_and_statements(
    payments: Iterable[Any],
    statements: Iterable[Any],
    fuzzy_threshold: float = 0.80,
    *,
    fee_tolerance: Decimal = Decimal("0"),
    max_date_gap_days: int = 7,
) -> ReconciliationReport:
    """Reconcile payment orders against executed statement transactions.

    Executes multi-pass matching:
    1. Exact End-to-End Reference match (`EndToEndId` or `pmt_inf_id`).
    2. Exact Amount + Exact Currency + Counterparty Name match.
    3. Amount Match with Fuzzy Name / Remittance text comparison.
    4. Partial Amount Deduction (where statement amount + known fee == payment amount).

    Args:
        payments: Sequence of payment instruction records (e.g. from PAIN.001).
        statements: Sequence of statement transaction records (e.g. from CAMT.053).
        fuzzy_threshold: String similarity score threshold (0.0 to 1.0) for fuzzy pass.
        fee_tolerance: Explicit maximum settlement deduction; zero disables it.
        max_date_gap_days: Maximum gap when both records provide dates.

    Amounts in PAIN InstdAmt are unsigned outgoing instructions. Other amount
    fields must carry the same sign as the statement. Currency is required.
    Conflicting account IDs, references, dates, and ambiguous candidates remain
    unmatched. Missing dates/accounts cannot establish those dimensions.
    Reconciled volumes are absolute settled amounts grouped by currency.
    The legacy total is None when matches span multiple currencies; no FX
    conversion is inferred. Unrecognized explicit directions raise ValueError.

    Returns:
        Structured ReconciliationReport.
    """
    pmt_list = [_to_record_dict(p) for p in payments]
    stmt_list = [_to_record_dict(s) for s in statements]

    matched_pmt_indices: set[int] = set()
    matched_stmt_indices: set[int] = set()
    matches: list[ReconciliationMatch] = []
    volumes: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))

    if not 0 <= fuzzy_threshold <= 1:
        raise ValueError("fuzzy_threshold must be between zero and one")
    if (
        not fee_tolerance.is_finite()
        or fee_tolerance < 0
        or max_date_gap_days < 0
    ):
        raise ValueError(
            "fee tolerance and date gap must be finite and nonnegative"
        )

    def fields(
        record: dict[str, Any], payment: bool
    ) -> tuple[Decimal, str, str, str, str, date | None]:
        """Normalize financial matching keys once per input record."""
        amount = _extract_amount(
            _get_val(record, "InstdAmt", "Amount", "amount", "amt")
        )
        if payment and "InstdAmt" in record:
            amount = -abs(amount)
        direction = _get_val(record, "DrCr", "credit_debit").upper()
        if direction in {"DBIT", "DEBIT", "D", "DR"}:
            amount = -abs(amount)
        elif direction in {"CRDT", "CREDIT", "C", "CR"}:
            amount = abs(amount)
        elif direction:
            raise ValueError(
                f"Unsupported credit/debit direction: {direction!r}"
            )
        currency = _get_val(record, "Currency", "currency", "curr").upper()
        reference = _get_val(
            record,
            "EndToEndId",
            "end_to_end_id",
            "reference",
            "Reference",
            "ref_id",
        ).casefold()
        if reference in {"notprovided", "nonref"}:
            reference = ""
        party = _get_val(
            record,
            "CdtrNm",
            "Creditor",
            "counterparty",
            "creditor_name",
            "recipient",
            "description",
            "Description",
        ).casefold()
        account = _get_val(record, "DbtrIBAN", "AccountId", "account_id")
        day = _get_val(
            record, "booking_date", "BookgDt", "ReqdExctnDt", "date"
        )
        parsed_day = _parse_date(day)
        return amount, currency, reference, party, account, parsed_day

    p_fields = [fields(p, True) for p in pmt_list]
    s_fields = [fields(s, False) for s in stmt_list]
    ref_index: dict[tuple[str, Any], list[int]] = defaultdict(list)
    amount_index: dict[tuple[str, Any], list[int]] = defaultdict(list)
    for i, (amount, curr, ref, *_rest) in enumerate(s_fields):
        if ref:
            ref_index[(curr, ref)].append(i)
        amount_index[(curr, amount)].append(i)

    def compatible(
        p: tuple[Decimal, str, str, str, str, date | None],
        s: tuple[Decimal, str, str, str, str, date | None],
    ) -> bool:
        """Reject contradictory identity and settlement evidence."""
        return bool(
            p[1]
            and p[1] == s[1]
            and p[0] * s[0] > 0
            and (not p[4] or not s[4] or p[4] == s[4])
            and (
                not p[5]
                or not s[5]
                or abs((p[5] - s[5]).days) <= max_date_gap_days
            )
            and (not p[2] or not s[2] or p[2] == s[2])
        )

    # Pass 1: Exact Reference Match (EndToEndId / Reference).
    # Pass 2: Exact Amount + Exact Currency + Exact Counterparty Name.
    # Pass 3: Exact Amount + Fuzzy Name / Remittance Similarity.
    # Indexed candidates avoid scanning unrelated amounts and currencies.
    for match_pass in range(3):
        proposals: dict[
            int, list[tuple[int, ReconciliationStatus, float, Decimal]]
        ] = defaultdict(list)
        for p_idx, p in enumerate(p_fields):
            if p_idx in matched_pmt_indices:
                continue
            candidates = (
                ref_index.get((p[1], p[2]), [])
                if match_pass == 0 and p[2]
                else amount_index.get((p[1], p[0]), [])
                if match_pass > 0
                else []
            )
            eligible = []
            for s_idx in candidates:
                s = s_fields[s_idx]
                if s_idx in matched_stmt_indices or not compatible(p, s):
                    continue
                diff = abs(p[0]) - abs(s[0])
                if match_pass == 0:
                    if not 0 <= diff <= fee_tolerance:
                        continue
                    status = (
                        ReconciliationStatus.EXACT_REFERENCE
                        if diff == 0
                        else ReconciliationStatus.PARTIAL_AMOUNT_DEDUCTION
                    )
                    confidence = 1.0 if diff == 0 else 0.9
                elif not p[3] or not s[3]:
                    continue
                elif match_pass == 1:
                    if p[3] != s[3]:
                        continue
                    status, confidence = (
                        ReconciliationStatus.EXACT_AMOUNT_AND_PARTY,
                        0.98,
                    )
                else:
                    confidence = difflib.SequenceMatcher(
                        None, p[3], s[3]
                    ).ratio()
                    if confidence < fuzzy_threshold:
                        continue
                    status = ReconciliationStatus.FUZZY_MATCH
                eligible.append((s_idx, status, confidence, diff))
            if len(eligible) == 1:
                s_idx, status, confidence, diff = eligible[0]
                proposals[s_idx].append((p_idx, status, confidence, diff))
        # Require uniqueness in both directions: never take the first of ties.
        for s_idx, options in proposals.items():
            if len(options) != 1:
                continue
            p_idx, status, confidence, diff = options[0]
            matched_pmt_indices.add(p_idx)
            matched_stmt_indices.add(s_idx)
            volumes[s_fields[s_idx][1]] += abs(s_fields[s_idx][0])
            matches.append(
                ReconciliationMatch(
                    status=status,
                    confidence=round(confidence, 2),
                    payment_record=pmt_list[p_idx],
                    statement_record=stmt_list[s_idx],
                    amount_difference=diff,
                    matched_on=status.value,
                )
            )

    unmatched_pmts = [
        p for idx, p in enumerate(pmt_list) if idx not in matched_pmt_indices
    ]
    unmatched_stmts = [
        s for idx, s in enumerate(stmt_list) if idx not in matched_stmt_indices
    ]

    total_items = len(pmt_list)
    match_rate = (
        round(len(matches) / total_items, 4) if total_items > 0 else 1.00
    )
    partial_count = sum(
        1
        for m in matches
        if m.status == ReconciliationStatus.PARTIAL_AMOUNT_DEDUCTION
    )

    return ReconciliationReport(
        total_payments=len(pmt_list),
        total_statements=len(stmt_list),
        matched_count=len(matches),
        unmatched_payment_count=len(unmatched_pmts),
        unmatched_statement_count=len(unmatched_stmts),
        partial_deduction_count=partial_count,
        match_rate=match_rate,
        total_reconciled_volume=(
            next(iter(volumes.values()), Decimal("0.00"))
            if len(volumes) <= 1
            else None
        ),
        reconciled_volume_by_currency=dict(volumes),
        matches=matches,
        unmatched_payments=unmatched_pmts,
        unmatched_statements=unmatched_stmts,
    )
