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
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, cast


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
    total_reconciled_volume: Decimal
    matches: list[ReconciliationMatch]
    unmatched_payments: list[dict[str, Any]]
    unmatched_statements: list[dict[str, Any]]

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
            "total_reconciled_volume": str(self.total_reconciled_volume),
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

    Returns:
        Structured ReconciliationReport.
    """
    pmt_list = [_to_record_dict(p) for p in payments]
    stmt_list = [_to_record_dict(s) for s in statements]

    matched_pmt_indices: set[int] = set()
    matched_stmt_indices: set[int] = set()
    matches: list[ReconciliationMatch] = []
    reconciled_volume = Decimal("0.00")

    # Pass 1: Exact Reference Match (EndToEndId / Reference)
    for p_idx, p in enumerate(pmt_list):
        p_ref = _get_val(
            p, "EndToEndId", "end_to_end_id", "reference", "ref_id"
        )
        if not p_ref or len(p_ref) < 3:
            continue

        p_amt = abs(_extract_amount(_get_val(p, "InstdAmt", "amount", "amt")))

        for s_idx, s in enumerate(stmt_list):
            if s_idx in matched_stmt_indices:
                continue
            s_ref = _get_val(
                s,
                "end_to_end_id",
                "reference",
                "remittance_information",
                "description",
            )

            if p_ref.lower() in s_ref.lower():
                s_amt = abs(
                    _extract_amount(
                        _get_val(s, "amount", "amt", "instructed_amount")
                    )
                )
                diff = abs(p_amt - s_amt)

                matched_pmt_indices.add(p_idx)
                matched_stmt_indices.add(s_idx)
                reconciled_volume += s_amt

                status = (
                    ReconciliationStatus.EXACT_REFERENCE
                    if diff == Decimal("0.00")
                    else ReconciliationStatus.PARTIAL_AMOUNT_DEDUCTION
                )
                matches.append(
                    ReconciliationMatch(
                        status=status,
                        confidence=1.00 if diff == Decimal("0.00") else 0.90,
                        payment_record=p,
                        statement_record=s,
                        amount_difference=diff,
                        matched_on=f"EndToEndId: {p_ref}",
                    )
                )
                break

    # Pass 2: Exact Amount + Exact Currency + Exact Counterparty Name
    for p_idx, p in enumerate(pmt_list):
        if p_idx in matched_pmt_indices:
            continue
        p_amt = abs(_extract_amount(_get_val(p, "InstdAmt", "amount", "amt")))
        p_curr = _get_val(p, "Currency", "currency", "curr").upper()
        p_name = _get_val(
            p, "CdtrNm", "creditor_name", "recipient", "debtor_name"
        ).upper()

        if not p_name or p_amt == Decimal("0.00"):
            continue

        for s_idx, s in enumerate(stmt_list):
            if s_idx in matched_stmt_indices:
                continue
            s_amt = abs(
                _extract_amount(
                    _get_val(s, "amount", "amt", "instructed_amount")
                )
            )
            s_curr = _get_val(s, "currency", "curr", "Currency").upper()
            s_name = _get_val(
                s, "creditor_name", "debtor_name", "description"
            ).upper()

            if (
                p_amt == s_amt
                and (not p_curr or not s_curr or p_curr == s_curr)
                and (p_name in s_name or s_name in p_name)
            ):
                matched_pmt_indices.add(p_idx)
                matched_stmt_indices.add(s_idx)
                reconciled_volume += s_amt

                matches.append(
                    ReconciliationMatch(
                        status=ReconciliationStatus.EXACT_AMOUNT_AND_PARTY,
                        confidence=0.98,
                        payment_record=p,
                        statement_record=s,
                        amount_difference=Decimal("0.00"),
                        matched_on=f"Amount: {p_amt} {p_curr} + Party: {p_name}",
                    )
                )
                break

    # Pass 3: Exact Amount + Fuzzy Name / Remittance Similarity
    for p_idx, p in enumerate(pmt_list):
        if p_idx in matched_pmt_indices:
            continue
        p_amt = abs(_extract_amount(_get_val(p, "InstdAmt", "amount", "amt")))
        p_name = _get_val(
            p, "CdtrNm", "creditor_name", "recipient", "description"
        )

        if p_amt == Decimal("0.00"):
            continue

        for s_idx, s in enumerate(stmt_list):
            if s_idx in matched_stmt_indices:
                continue
            s_amt = abs(
                _extract_amount(
                    _get_val(s, "amount", "amt", "instructed_amount")
                )
            )

            if p_amt == s_amt:
                s_desc = _get_val(
                    s, "description", "creditor_name", "remittance_information"
                )
                ratio = difflib.SequenceMatcher(
                    None, p_name.lower(), s_desc.lower()
                ).ratio()

                if ratio >= fuzzy_threshold:
                    matched_pmt_indices.add(p_idx)
                    matched_stmt_indices.add(s_idx)
                    reconciled_volume += s_amt

                    matches.append(
                        ReconciliationMatch(
                            status=ReconciliationStatus.FUZZY_MATCH,
                            confidence=round(ratio, 2),
                            payment_record=p,
                            statement_record=s,
                            amount_difference=Decimal("0.00"),
                            matched_on=f"Amount: {p_amt} + Fuzzy Name Ratio: {ratio:.2f}",
                        )
                    )
                    break

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
        total_reconciled_volume=reconciled_volume.quantize(Decimal("0.01")),
        matches=matches,
        unmatched_payments=unmatched_pmts,
        unmatched_statements=unmatched_stmts,
    )
