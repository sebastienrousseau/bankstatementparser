"""Tests for optional Polars export helpers."""

from __future__ import annotations

import sys
from types import ModuleType

import pandas as pd
import pytest

from bankstatementparser.base_parser import BankStatementParser


class _DummyParser(BankStatementParser):
    def parse(self) -> pd.DataFrame:
        return pd.DataFrame([{"amount": 1.0, "currency": "EUR"}])

    def get_summary(self) -> dict[str, object]:
        return {"account_id": "acct-1", "transaction_count": 1}


def test_to_polars_raises_clear_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = _DummyParser("dummy.csv")
    monkeypatch.setitem(sys.modules, "polars", None)

    with pytest.raises(ImportError, match="bankstatementparser\\[polars\\]"):
        parser.to_polars()


def test_to_polars_and_lazy_use_optional_polars_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = _DummyParser("dummy.csv")

    class _FakePolarsFrame:
        def __init__(self, payload: pd.DataFrame) -> None:
            self.payload = payload

        def lazy(self) -> str:
            return "lazy-frame"

    fake_module = ModuleType("polars")
    fake_module.from_pandas = lambda payload: _FakePolarsFrame(payload)
    monkeypatch.setitem(sys.modules, "polars", fake_module)

    frame = parser.to_polars()

    assert frame.payload.equals(parser.parse())
    assert parser.to_polars_lazy() == "lazy-frame"
