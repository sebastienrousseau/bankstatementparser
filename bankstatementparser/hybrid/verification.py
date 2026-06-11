# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Golden Rule balance verification.

If ``opening + credits - debits != closing`` the statement is flagged
as ``Discrepancy`` (or ``Failed`` when balances are missing). This is
the single most important integrity check in the hybrid pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from itertools import pairwise
from typing import Optional

from ..transaction_models import Transaction


class VerificationStatus(str, Enum):
    """Verification outcome for a parsed statement."""

    VERIFIED = "verified"
    DISCREPANCY = "discrepancy"
    FAILED = "failed"


@dataclass(frozen=True)
class BalanceVerification:
    """Result of running the Golden Rule balance check."""

    status: VerificationStatus
    opening_balance: Optional[Decimal]
    closing_balance: Optional[Decimal]
    total_credits: Decimal
    total_debits: Decimal
    expected_delta: Optional[Decimal]
    actual_delta: Decimal
    discrepancy: Optional[Decimal]
    message: str


def verify_balance(
    transactions: Iterable[Transaction],
    *,
    opening_balance: Optional[Decimal],
    closing_balance: Optional[Decimal],
    tolerance: Decimal = Decimal("0.01"),
) -> BalanceVerification:
    """Run the Golden Rule on a transaction set.

    Args:
        transactions: Iterable of normalized transactions. Debits are
            represented as negative amounts and credits as positive.
        opening_balance: Statement opening balance, or ``None`` if the
            source did not provide it.
        closing_balance: Statement closing balance, or ``None``.
        tolerance: Allowed absolute drift before flagging a
            discrepancy. Defaults to one cent.

    Returns:
        A :class:`BalanceVerification` describing the outcome. The
        ``status`` is ``FAILED`` only when the rule cannot be applied
        (missing balances), not when it disagrees.
    """
    credits = Decimal("0")
    debits = Decimal("0")
    for tx in transactions:
        if tx.amount >= 0:
            credits += tx.amount
        else:
            debits += -tx.amount

    actual_delta = credits - debits

    if opening_balance is None or closing_balance is None:
        return BalanceVerification(
            status=VerificationStatus.FAILED,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            total_credits=credits,
            total_debits=debits,
            expected_delta=None,
            actual_delta=actual_delta,
            discrepancy=None,
            message=("Cannot verify: missing opening or closing balance"),
        )

    expected_delta = closing_balance - opening_balance
    discrepancy = actual_delta - expected_delta
    if abs(discrepancy) <= tolerance:
        return BalanceVerification(
            status=VerificationStatus.VERIFIED,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            total_credits=credits,
            total_debits=debits,
            expected_delta=expected_delta,
            actual_delta=actual_delta,
            discrepancy=discrepancy,
            message="Balance verified within tolerance",
        )

    return BalanceVerification(
        status=VerificationStatus.DISCREPANCY,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        total_credits=credits,
        total_debits=debits,
        expected_delta=expected_delta,
        actual_delta=actual_delta,
        discrepancy=discrepancy,
        message=(
            f"Balance mismatch: expected delta {expected_delta}, "
            f"actual {actual_delta} (off by {discrepancy})"
        ),
    )


def verify_balance_multi_currency(
    transactions: Iterable[Transaction],
    *,
    balances: Optional[dict[str, tuple[Decimal, Decimal]]] = None,
    tolerance: Decimal = Decimal("0.01"),
) -> dict[str, BalanceVerification]:
    """Run the Golden Rule **per currency**.

    Multi-currency statements (common in international business
    banking) mix transactions in different currencies. The single-
    currency :func:`verify_balance` would always report
    ``DISCREPANCY`` because it sums GBP and EUR amounts together.

    This function groups transactions by ``Transaction.currency``
    and runs an independent Golden Rule check for each group.

    Args:
        transactions: Iterable of normalized transactions.
        balances: Optional ``{currency: (opening, closing)}`` dict.
            When ``None``, verification runs with ``FAILED`` status
            for every currency (no balances provided). When a
            currency appears in the transactions but not in this
            dict, its verification is also ``FAILED``.
        tolerance: Per-currency tolerance. Defaults to one cent.

    Returns:
        A dict mapping each currency code (uppercase) to its
        :class:`BalanceVerification`. Transactions with
        ``currency=None`` are grouped under the key ``"UNKNOWN"``.
    """
    balances = balances or {}
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for tx in transactions:
        key = (tx.currency or "UNKNOWN").upper()
        groups[key].append(tx)

    results: dict[str, BalanceVerification] = {}
    for currency, txs in sorted(groups.items()):
        pair = balances.get(currency)
        opening = pair[0] if pair else None
        closing = pair[1] if pair else None
        results[currency] = verify_balance(
            txs,
            opening_balance=opening,
            closing_balance=closing,
            tolerance=tolerance,
        )
    return results


def aggregate_verifications(
    results: dict[str, BalanceVerification],
) -> BalanceVerification:
    """Collapse per-currency results into one statement-level verdict.

    The aggregate ``status`` is the worst per-currency outcome:
    ``DISCREPANCY`` if any currency disagrees, else ``FAILED`` if any
    currency could not be checked, else ``VERIFIED``.

    ``total_credits``/``total_debits``/``actual_delta`` are raw sums
    across all currencies — useful as row-count-style magnitudes, not
    as monetary values. ``opening_balance``, ``closing_balance``,
    ``expected_delta``, and ``discrepancy`` are ``None`` because they
    have no single-currency meaning. Per-currency detail is carried
    in ``message``.

    Args:
        results: Output of :func:`verify_balance_multi_currency`.
            Must be non-empty.

    Returns:
        A single :class:`BalanceVerification` summarizing all
        currencies.

    Raises:
        ValueError: If ``results`` is empty.
    """
    if not results:
        raise ValueError("aggregate_verifications requires results")

    statuses = {v.status for v in results.values()}
    if VerificationStatus.DISCREPANCY in statuses:
        status = VerificationStatus.DISCREPANCY
    elif VerificationStatus.FAILED in statuses:
        status = VerificationStatus.FAILED
    else:
        status = VerificationStatus.VERIFIED

    credits = sum((v.total_credits for v in results.values()), Decimal("0"))
    debits = sum((v.total_debits for v in results.values()), Decimal("0"))

    detail = "; ".join(
        f"{currency}: {v.status.value} ({v.message})"
        for currency, v in sorted(results.items())
    )
    return BalanceVerification(
        status=status,
        opening_balance=None,
        closing_balance=None,
        total_credits=credits,
        total_debits=debits,
        expected_delta=None,
        actual_delta=credits - debits,
        discrepancy=None,
        message=f"Multi-currency statement — {detail}",
    )


@dataclass(frozen=True)
class ContinuityBreak:
    """A broken link between two consecutive statements."""

    previous_label: str
    next_label: str
    previous_closing: Decimal
    next_opening: Decimal
    gap: Decimal


@dataclass(frozen=True)
class ContinuityResult:
    """Result of running the cross-statement continuity check."""

    status: VerificationStatus
    breaks: tuple[ContinuityBreak, ...]
    checked_links: int
    unchecked_links: int
    message: str


def verify_continuity(
    statements: Sequence[tuple[str, Optional[Decimal], Optional[Decimal]]],
    *,
    tolerance: Decimal = Decimal("0.01"),
) -> ContinuityResult:
    """Check that consecutive statements chain without a gap.

    The closing balance of statement N must equal the opening balance
    of statement N+1 — the natural extension of the Golden Rule for
    anyone batch-processing a folder of monthly statements. A missing
    month, a duplicated export, or an LLM that hallucinated a balance
    all show up as a continuity break.

    Args:
        statements: ``(label, opening_balance, closing_balance)``
            triples in statement order (oldest first). Labels are
            free-form — typically file paths or period names — and
            are echoed back in any reported break.
        tolerance: Allowed absolute gap per link. Defaults to one
            cent.

    Returns:
        A :class:`ContinuityResult`. ``status`` is ``DISCREPANCY``
        if any link has a gap beyond tolerance, else ``FAILED`` if
        any link could not be checked (missing balance on either
        side, or fewer than two statements), else ``VERIFIED``.
    """
    if len(statements) < 2:
        return ContinuityResult(
            status=VerificationStatus.FAILED,
            breaks=(),
            checked_links=0,
            unchecked_links=0,
            message=("Cannot verify continuity: need at least two statements"),
        )

    breaks: list[ContinuityBreak] = []
    checked = 0
    unchecked = 0
    for previous, current in pairwise(statements):
        prev_label, _, prev_closing = previous
        next_label, next_opening, _ = current
        if prev_closing is None or next_opening is None:
            unchecked += 1
            continue
        checked += 1
        gap = next_opening - prev_closing
        if abs(gap) > tolerance:
            breaks.append(
                ContinuityBreak(
                    previous_label=prev_label,
                    next_label=next_label,
                    previous_closing=prev_closing,
                    next_opening=next_opening,
                    gap=gap,
                )
            )

    if breaks:
        detail = "; ".join(
            f"{b.previous_label} closed at {b.previous_closing} but "
            f"{b.next_label} opened at {b.next_opening} "
            f"(gap {b.gap})"
            for b in breaks
        )
        return ContinuityResult(
            status=VerificationStatus.DISCREPANCY,
            breaks=tuple(breaks),
            checked_links=checked,
            unchecked_links=unchecked,
            message=f"Continuity broken: {detail}",
        )
    if unchecked:
        return ContinuityResult(
            status=VerificationStatus.FAILED,
            breaks=(),
            checked_links=checked,
            unchecked_links=unchecked,
            message=(
                f"Continuity incomplete: {unchecked} of "
                f"{checked + unchecked} links missing a balance"
            ),
        )
    return ContinuityResult(
        status=VerificationStatus.VERIFIED,
        breaks=(),
        checked_links=checked,
        unchecked_links=unchecked,
        message=f"Continuity verified across {checked + 1} statements",
    )


def verify_transactions(
    transactions: Iterable[Transaction],
    *,
    opening_balance: Optional[Decimal],
    closing_balance: Optional[Decimal],
    tolerance: Decimal = Decimal("0.01"),
) -> BalanceVerification:
    """Run the Golden Rule, currency-aware.

    Single-currency statements (or statements with no currency
    metadata at all) go through :func:`verify_balance` unchanged.
    When the transactions span more than one currency, summing them
    together would always produce a false ``DISCREPANCY``, so each
    currency is checked independently via
    :func:`verify_balance_multi_currency` and the per-currency
    results are collapsed with :func:`aggregate_verifications`.

    The single ``opening_balance``/``closing_balance`` pair cannot
    be attributed to one currency of a multi-currency statement, so
    in that case every currency reports ``FAILED`` (cannot verify)
    rather than a spurious mismatch.

    Args:
        transactions: Iterable of normalized transactions.
        opening_balance: Statement opening balance, or ``None``.
        closing_balance: Statement closing balance, or ``None``.
        tolerance: Allowed absolute drift. Defaults to one cent.

    Returns:
        A single statement-level :class:`BalanceVerification`.
    """
    txs = tuple(transactions)
    currencies = {tx.currency for tx in txs if tx.currency}
    if len(currencies) <= 1:
        return verify_balance(
            txs,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            tolerance=tolerance,
        )
    return aggregate_verifications(
        verify_balance_multi_currency(txs, tolerance=tolerance)
    )
