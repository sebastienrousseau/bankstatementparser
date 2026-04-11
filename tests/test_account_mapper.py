# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for the account mapping rules (#v0.0.8)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from bankstatementparser import Transaction
from bankstatementparser.enrichment.account_mapper import (
    AccountMapper,
    AccountRule,
)


def _tx(desc: str) -> Transaction:
    return Transaction(amount=Decimal("10"), description=desc)


def test_first_matching_rule_wins() -> None:
    mapper = AccountMapper(
        rules=[
            AccountRule(pattern="COFFEE", account="Expenses:Coffee"),
            AccountRule(pattern="COFFEE|TEA", account="Expenses:Drinks"),
        ]
    )
    assert mapper.map(_tx("STARBUCKS COFFEE")) == "Expenses:Coffee"


def test_default_when_no_match() -> None:
    mapper = AccountMapper(
        rules=[AccountRule(pattern="SALARY", account="Income:Salary")],
        default="Expenses:Other",
    )
    assert mapper.map(_tx("RANDOM MERCHANT")) == "Expenses:Other"


def test_case_insensitive_matching() -> None:
    mapper = AccountMapper(
        rules=[AccountRule(pattern="coffee", account="Expenses:Coffee")]
    )
    assert mapper.map(_tx("CARD PAYMENT COFFEE SHOP")) == "Expenses:Coffee"


def test_regex_pattern() -> None:
    mapper = AccountMapper(
        rules=[
            AccountRule(
                pattern=r"AMZN|AMAZON|AMZN MKTPLACE",
                account="Expenses:Shopping:Amazon",
            )
        ]
    )
    assert mapper.map(_tx("AMZN MKTPLACE 2026-04-01")) == "Expenses:Shopping:Amazon"
    assert mapper.map(_tx("AMAZON.CO.UK")) == "Expenses:Shopping:Amazon"


def test_invalid_regex_raises_at_construction() -> None:
    with pytest.raises(ValueError, match="Invalid regex"):
        AccountRule(pattern="[invalid", account="Expenses:Bad")


def test_map_batch() -> None:
    mapper = AccountMapper(
        rules=[
            AccountRule(pattern="SALARY", account="Income:Salary"),
            AccountRule(pattern="RENT", account="Expenses:Housing"),
        ]
    )
    txs = [_tx("SALARY ACME"), _tx("RENT PAYMENT"), _tx("COFFEE")]
    accounts = mapper.map_batch(txs)
    assert accounts == [
        "Income:Salary",
        "Expenses:Housing",
        "Expenses:Uncategorized",
    ]


def test_none_description_uses_default() -> None:
    mapper = AccountMapper(
        rules=[AccountRule(pattern="x", account="Expenses:X")]
    )
    tx = Transaction(amount=Decimal("10"))
    assert mapper.map(tx) == "Expenses:Uncategorized"


def test_from_json(tmp_path: Path) -> None:
    config = {
        "default": "Expenses:Misc",
        "rules": [
            {"pattern": "COFFEE", "account": "Expenses:Food:Coffee"},
            {"pattern": "SALARY", "account": "Income:Salary"},
        ],
    }
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(config))

    mapper = AccountMapper.from_json(path)
    assert mapper.default == "Expenses:Misc"
    assert len(mapper.rules) == 2
    assert mapper.map(_tx("COFFEE SHOP")) == "Expenses:Food:Coffee"
    assert mapper.map(_tx("MONTHLY SALARY")) == "Income:Salary"
    assert mapper.map(_tx("RANDOM")) == "Expenses:Misc"


def test_from_json_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[1, 2, 3]")
    with pytest.raises(ValueError, match="must be an object"):
        AccountMapper.from_json(path)


def test_from_json_skips_non_dict_rules(tmp_path: Path) -> None:
    config = {
        "rules": [
            {"pattern": "COFFEE", "account": "Expenses:Coffee"},
            "not a dict",
        ]
    }
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(config))
    mapper = AccountMapper.from_json(path)
    assert len(mapper.rules) == 1


def test_empty_rules_always_returns_default() -> None:
    mapper = AccountMapper()
    assert mapper.map(_tx("ANYTHING")) == "Expenses:Uncategorized"
