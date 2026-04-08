# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the hybrid smart_ingest orchestrator."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bankstatementparser.hybrid import orchestrator
from bankstatementparser.hybrid.llm_extractor import LLMExtractor
from bankstatementparser.hybrid.orchestrator import (
    LOW_TEXT_DENSITY_THRESHOLD,
    smart_ingest,
)
from bankstatementparser.hybrid.verification import VerificationStatus
from bankstatementparser.hybrid.vision import (
    VisionExtractor,
    VisionExtractorError,
)

# ---------------------------------------------------------------------------
# Deterministic path
# ---------------------------------------------------------------------------


class _FakeParser:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records

    def parse(self) -> list[dict[str, Any]]:
        return self._records


def test_smart_ingest_uses_deterministic_parser_when_format_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "statement.csv"
    file_path.write_text("placeholder")

    records = [
        {
            "account_id": "GB12BANK00001",
            "currency": "GBP",
            "amount": "100.00",
            "date": "2026-04-01",
            "description": "Salary",
        },
        {
            "account_id": "GB12BANK00001",
            "currency": "GBP",
            "amount": "-30.00",
            "date": "2026-04-02",
            "description": "Coffee",
        },
    ]

    monkeypatch.setattr(
        orchestrator,
        "detect_statement_format",
        lambda _path: "csv",
    )
    monkeypatch.setattr(
        orchestrator,
        "create_parser",
        lambda _path, _fmt: _FakeParser(records),
    )

    result = smart_ingest(file_path)

    assert result.source_method == "deterministic"
    assert result.source_format == "csv"
    assert len(result.transactions) == 2
    assert result.transactions[0].source_method == "deterministic"
    assert result.transactions[0].transaction_hash
    assert result.warnings == []


def test_smart_ingest_runs_balance_check_when_balances_provided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "statement.csv"
    file_path.write_text("placeholder")

    records = [
        {
            "account_id": "A",
            "currency": "GBP",
            "amount": "100.00",
            "date": "2026-04-01",
            "description": "Credit",
        },
        {
            "account_id": "A",
            "currency": "GBP",
            "amount": "-25.00",
            "date": "2026-04-02",
            "description": "Debit",
        },
    ]
    monkeypatch.setattr(
        orchestrator, "detect_statement_format", lambda _p: "csv"
    )
    monkeypatch.setattr(
        orchestrator,
        "create_parser",
        lambda _p, _f: _FakeParser(records),
    )

    result = smart_ingest(
        file_path,
        opening_balance=Decimal("500"),
        closing_balance=Decimal("575"),
    )
    assert result.verification is not None
    assert result.verification.status is VerificationStatus.VERIFIED


def test_smart_ingest_falls_back_to_llm_when_parser_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "statement.csv"
    file_path.write_text("placeholder")

    monkeypatch.setattr(
        orchestrator, "detect_statement_format", lambda _p: "csv"
    )

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(orchestrator, "create_parser", boom)
    monkeypatch.setattr(
        orchestrator, "extract_text", lambda _p: "raw pdf text " * 10
    )

    payload = {
        "opening_balance": "100",
        "closing_balance": "100",
        "transactions": [],
    }

    extractor = LLMExtractor(
        completion_fn=lambda **_: {
            "choices": [{"message": {"content": json.dumps(payload)}}]
        }
    )

    result = smart_ingest(file_path, extractor=extractor)
    assert result.source_method == "llm"
    assert any("failed" in w for w in result.warnings)


def test_smart_ingest_warns_when_detection_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "statement.pdf"
    file_path.write_text("placeholder")

    def boom(_path: str) -> str:
        raise RuntimeError("detector blew up")

    monkeypatch.setattr(
        orchestrator, "detect_statement_format", boom
    )
    monkeypatch.setattr(
        orchestrator, "extract_text", lambda _p: "pdf text " * 20
    )

    payload = {
        "opening_balance": "0",
        "closing_balance": "0",
        "transactions": [],
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: {
            "choices": [{"message": {"content": json.dumps(payload)}}]
        }
    )
    result = smart_ingest(file_path, extractor=extractor)
    assert result.source_method == "llm"
    assert any("detection failed" in w for w in result.warnings)


def test_smart_ingest_uses_llm_for_pdf_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "statement.pdf"
    file_path.write_text("placeholder")

    monkeypatch.setattr(
        orchestrator, "detect_statement_format", lambda _p: "pdf"
    )
    monkeypatch.setattr(
        orchestrator, "extract_text", lambda _p: "raw pdf text " * 10
    )

    payload = {
        "account_id": "GB1",
        "currency": "GBP",
        "opening_balance": "1000.00",
        "closing_balance": "950.00",
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Lunch",
                "amount": -50.00,
                "reference": None,
                "confidence": 0.9,
            }
        ],
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: {
            "choices": [{"message": {"content": json.dumps(payload)}}]
        }
    )
    result = smart_ingest(file_path, extractor=extractor)
    assert result.source_method == "llm"
    assert result.source_format == "pdf"
    assert len(result.transactions) == 1
    assert result.verification is not None
    assert result.verification.status is VerificationStatus.VERIFIED


def test_smart_ingest_explicit_balances_override_llm_balances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "statement.pdf"
    file_path.write_text("placeholder")

    monkeypatch.setattr(
        orchestrator, "detect_statement_format", lambda _p: None
    )
    monkeypatch.setattr(
        orchestrator, "extract_text", lambda _p: "text " * 30
    )

    payload = {
        "opening_balance": "0.00",
        "closing_balance": "0.00",
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "x",
                "amount": 10.00,
                "reference": None,
                "confidence": 1.0,
            }
        ],
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: {
            "choices": [{"message": {"content": json.dumps(payload)}}]
        }
    )
    result = smart_ingest(
        file_path,
        extractor=extractor,
        opening_balance=Decimal("100"),
        closing_balance=Decimal("110"),
    )
    assert result.verification is not None
    assert result.verification.status is VerificationStatus.VERIFIED


def test_coerce_transactions_handles_list_records() -> None:
    raw = [
        {"amount": "10.00", "date": "2026-04-01", "description": "x"},
        "not a dict",
    ]
    txs = orchestrator._coerce_transactions(raw, source="csv")
    assert len(txs) == 1


def test_coerce_transactions_handles_single_dict() -> None:
    raw = {"amount": "10.00", "date": "2026-04-01", "description": "x"}
    txs = orchestrator._coerce_transactions(raw, source="csv")
    assert len(txs) == 1


def test_coerce_transactions_handles_none() -> None:
    assert orchestrator._coerce_transactions(None, source="csv") == []


def test_smart_ingest_routes_scanned_pdf_to_vision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "scan.pdf"
    file_path.write_text("x")

    monkeypatch.setattr(
        orchestrator, "detect_statement_format", lambda _p: None
    )
    # Low-density text: below LOW_TEXT_DENSITY_THRESHOLD
    monkeypatch.setattr(
        orchestrator, "extract_text", lambda _p: "  \n  "
    )

    payload = {
        "opening_balance": "100.00",
        "closing_balance": "90.00",
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Scanned line",
                "amount": -10.00,
                "reference": None,
                "confidence": 0.8,
            }
        ],
    }
    vision = VisionExtractor(
        model="ollama/llava",
        completion_fn=lambda **_: {
            "choices": [{"message": {"content": json.dumps(payload)}}]
        },
    )
    # Stub pypdfium2 so VisionExtractor._render_pages works
    import sys
    import types

    fake = types.ModuleType("pypdfium2")

    class _Bitmap:
        def to_pil(self) -> Any:
            class _P:
                def save(self, buf: Any, format: str) -> None:  # noqa: A002
                    buf.write(b"PNG")

            return _P()

    class _Page:
        def render(self, scale: float) -> _Bitmap:
            return _Bitmap()

    class _Doc:
        def __init__(self, _p: str) -> None:
            pass

        def __len__(self) -> int:
            return 1

        def __getitem__(self, i: int) -> _Page:
            return _Page()

    fake.PdfDocument = _Doc  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdfium2", fake)

    result = smart_ingest(file_path, vision_extractor=vision)
    assert result.source_method == "vision"
    assert result.source_format == "pdf"
    assert any(
        "LOW_TEXT_DENSITY" in w for w in result.warnings
    )
    assert result.verification is not None
    assert result.verification.status is VerificationStatus.VERIFIED


def test_smart_ingest_vision_raises_when_model_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "scan.pdf"
    file_path.write_text("x")

    monkeypatch.setattr(
        orchestrator, "detect_statement_format", lambda _p: "pdf"
    )
    monkeypatch.setattr(orchestrator, "extract_text", lambda _p: "")
    monkeypatch.delenv("BSP_HYBRID_VISION_MODEL", raising=False)

    with pytest.raises(
        VisionExtractorError, match="Vision model required"
    ):
        smart_ingest(file_path)


def test_low_text_density_threshold_is_positive() -> None:
    assert LOW_TEXT_DENSITY_THRESHOLD > 0


def test_coerce_transactions_handles_dataframe() -> None:
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "amount": "10.00",
                "date": "2026-04-01",
                "description": "x",
            }
        ]
    )
    txs = orchestrator._coerce_transactions(df, source="csv")
    assert len(txs) == 1


def test_coerce_transactions_skips_unparsable_rows() -> None:
    raw = [
        {"description": "missing amount"},
        {"amount": "5.00", "date": "2026-04-01", "description": "ok"},
    ]
    txs = orchestrator._coerce_transactions(raw, source="csv")
    assert len(txs) == 1
