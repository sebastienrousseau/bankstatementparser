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

"""Export transactions to hledger and beancount journal formats.

These formats are the two most popular plaintext-accounting file
formats. Both represent transactions as human-readable text files
that are version-controlled, diffable, and auditable — a natural
fit for bank statement data.

Usage::

    from bankstatementparser.export import to_hledger, to_beancount

    journal = to_hledger(transactions, account="Assets:Bank:Checking")
    Path("journal.ledger").write_text(journal)

    journal = to_beancount(transactions, account="Assets:Bank:Checking")
    Path("journal.beancount").write_text(journal)

No external dependencies — both functions produce plain strings.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..transaction_models import Transaction


def to_hledger(
    transactions: Iterable[Transaction],
    *,
    account: str = "Assets:Bank:Checking",
    contra_account: str = "Expenses:Uncategorized",
    default_currency: str = "EUR",
) -> str:
    """Render transactions as an hledger-compatible journal.

    Each transaction produces one journal entry with two postings:
    one to ``account`` (the bank account) and one to
    ``contra_account`` (the expense/income bucket). The
    ``contra_account`` posting has no explicit amount — hledger
    infers it as the negation.

    If the transaction has a ``category`` field set (from the
    enrichment module), it replaces ``contra_account`` for that
    entry.

    Args:
        transactions: Iterable of :class:`Transaction` objects.
        account: The bank account name in hledger format.
        contra_account: Default contra-account for uncategorized
            transactions.
        default_currency: Currency code when the transaction has
            no currency set.

    Returns:
        A string containing the full journal, ready to write to a
        ``.ledger`` or ``.journal`` file.
    """
    lines: list[str] = []
    for tx in transactions:
        date = (
            tx.booking_date.isoformat()
            if tx.booking_date is not None
            else "1970-01-01"
        )
        desc = _escape_description(tx.description or "Unknown")
        currency = tx.currency or default_currency
        amount = format(tx.amount.normalize(), "f")

        contra = _resolve_contra(tx, contra_account)

        lines.append(f"{date} {desc}")
        lines.append(f"    {account}    {currency} {amount}")
        lines.append(f"    {contra}")
        lines.append("")

    return "\n".join(lines)


def to_beancount(
    transactions: Iterable[Transaction],
    *,
    account: str = "Assets:Bank:Checking",
    contra_account: str = "Expenses:Uncategorized",
    default_currency: str = "EUR",
) -> str:
    """Render transactions as a beancount-compatible journal.

    Beancount uses a slightly different syntax from hledger:

    * The directive is ``txn`` (not implicit).
    * Amounts appear on both postings (beancount requires explicit
      amounts unless using ``pad`` directives).
    * The payee and narration are separate quoted fields.

    Args:
        transactions: Iterable of :class:`Transaction` objects.
        account: The bank account name in beancount format.
        contra_account: Default contra-account.
        default_currency: Currency code when the transaction has
            no currency set.

    Returns:
        A string containing the full journal.
    """
    lines: list[str] = []
    for tx in transactions:
        date = (
            tx.booking_date.isoformat()
            if tx.booking_date is not None
            else "1970-01-01"
        )
        payee = _escape_beancount_string(
            tx.counterparty or ""
        )
        narration = _escape_beancount_string(
            tx.description or "Unknown"
        )
        currency = tx.currency or default_currency
        amount = format(tx.amount.normalize(), "f")
        neg_amount = format((-tx.amount).normalize(), "f")

        contra = _resolve_contra(tx, contra_account)

        lines.append(f'{date} txn "{payee}" "{narration}"')
        lines.append(f"  {account}  {amount} {currency}")
        lines.append(f"  {contra}  {neg_amount} {currency}")
        lines.append("")

    return "\n".join(lines)


def _resolve_contra(
    tx: Transaction, default: str
) -> str:
    """Use the enrichment category as contra-account if available."""
    category = tx.category
    if category:
        safe = category.replace(" ", ":").replace("/", ":")
        return f"Expenses:{safe}"
    return default


def _escape_description(value: str) -> str:
    """Sanitize a description for hledger journal format."""
    return value.replace("\n", " ").replace("\r", "").strip()


def _escape_beancount_string(value: str) -> str:
    """Escape a string for beancount's quoted fields."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .strip()
    )
