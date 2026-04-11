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

"""Configurable account mapping for plaintext-accounting export.

Assigns a destination account to each transaction based on
description patterns. Designed to pair with the hledger/beancount
exporter — the categorizer (#44) answers "what category?" while the
account mapper answers "which ledger account?".

Usage::

    from bankstatementparser.enrichment.account_mapper import (
        AccountMapper,
        AccountRule,
    )

    rules = [
        AccountRule(pattern="COFFEE|STARBUCKS", account="Expenses:Food:Coffee"),
        AccountRule(pattern="SALARY", account="Income:Salary"),
        AccountRule(pattern="RENT", account="Expenses:Housing:Rent"),
    ]
    mapper = AccountMapper(rules=rules, default="Expenses:Uncategorized")

    for tx in transactions:
        account = mapper.map(tx)
        print(tx.description, "->", account)

Rules are evaluated top-to-bottom; the first match wins. Patterns
are compiled as case-insensitive regexes against the raw
description (not the normalized one, so the user sees the patterns
they'd expect from their bank's actual wording).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from ..transaction_models import Transaction

PathLike = Union[str, Path]


@dataclass(frozen=True)
class AccountRule:
    """A single pattern → account mapping rule.

    ``pattern`` is a case-insensitive regex matched against the
    transaction's raw ``description``. ``account`` is the ledger
    account name to assign when the pattern matches.
    """

    pattern: str
    account: str

    def __post_init__(self) -> None:
        # Validate the regex at construction time so bad patterns
        # fail loudly, not silently at map time.
        try:
            re.compile(self.pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(
                f"Invalid regex in AccountRule: {self.pattern!r}: {exc}"
            ) from exc


@dataclass
class AccountMapper:
    """Map transactions to ledger accounts via configurable rules.

    Rules are evaluated top-to-bottom; the first match wins. When
    no rule matches, ``default`` is returned.

    Args:
        rules: Ordered list of :class:`AccountRule` instances.
        default: Fallback account for unmatched transactions.
    """

    rules: list[AccountRule] = field(default_factory=list)
    default: str = "Expenses:Uncategorized"
    _compiled: list[tuple[re.Pattern[str], str]] = field(
        init=False, default_factory=list, repr=False
    )

    def __post_init__(self) -> None:
        self._compiled = [
            (re.compile(rule.pattern, re.IGNORECASE), rule.account)
            for rule in self.rules
        ]

    def map(self, transaction: Transaction) -> str:
        """Return the ledger account for a single transaction."""
        desc = transaction.description or ""
        for compiled_re, account in self._compiled:
            if compiled_re.search(desc):
                return account
        return self.default

    def map_batch(
        self, transactions: Iterable[Transaction]
    ) -> list[str]:
        """Map every transaction in a batch. Returns one account per row."""
        return [self.map(tx) for tx in transactions]

    @classmethod
    def from_json(cls, path: PathLike) -> AccountMapper:
        """Load rules from a JSON file.

        Expected format::

            {
                "default": "Expenses:Uncategorized",
                "rules": [
                    {"pattern": "COFFEE|STARBUCKS", "account": "Expenses:Food:Coffee"},
                    {"pattern": "SALARY", "account": "Income:Salary"}
                ]
            }
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Account mapping JSON must be an object")
        rules = [
            AccountRule(
                pattern=str(r.get("pattern", "")),
                account=str(r.get("account", "")),
            )
            for r in data.get("rules", [])
            if isinstance(r, dict)
        ]
        return cls(
            rules=rules,
            default=str(data.get("default", "Expenses:Uncategorized")),
        )
