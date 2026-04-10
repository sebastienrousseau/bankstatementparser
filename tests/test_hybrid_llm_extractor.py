# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the LiteLLM-backed extractor (with mocked completion)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from bankstatementparser.hybrid.llm_extractor import (
    LLMExtractor,
    LLMExtractorError,
)
from bankstatementparser.hybrid.prompts import build_messages


def _fake_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"content": json.dumps(payload)}}
        ]
    }


VALID_PAYLOAD: dict[str, Any] = {
    "account_id": "GB12BANK00001",
    "currency": "gbp",
    "opening_balance": "500.00",
    "closing_balance": "470.00",
    "transactions": [
        {
            "booking_date": "2026-04-01",
            "description": "Coffee Shop",
            "amount": -5.00,
            "reference": "CARD-001",
            "confidence": 0.95,
        },
        {
            "booking_date": "2026-04-02",
            "description": "Salary",
            "amount": 100.00,
            "reference": None,
            "confidence": 0.99,
        },
    ],
}


def test_extract_parses_well_formed_response() -> None:
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_response(VALID_PAYLOAD)

    extractor = LLMExtractor(
        model="ollama/llama3", completion_fn=fake_completion
    )
    result = extractor.extract("some statement text")

    assert captured["model"] == "ollama/llama3"
    assert captured["temperature"] == 0.0
    assert result.account_id == "GB12BANK00001"
    assert result.currency == "GBP"
    assert result.opening_balance == Decimal("500.00")
    assert result.closing_balance == Decimal("470.00")
    assert len(result.transactions) == 2
    first = result.transactions[0]
    assert first.amount == Decimal("-5.00")
    assert first.source_method == "llm"
    assert first.confidence == 0.95
    assert first.transaction_hash  # computed by the model


def test_extract_passes_api_base_when_set() -> None:
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_response(VALID_PAYLOAD)

    extractor = LLMExtractor(
        model="ollama/llama3",
        api_base="http://localhost:11434",
        completion_fn=fake_completion,
    )
    extractor.extract("statement")
    assert captured["api_base"] == "http://localhost:11434"


def test_extract_handles_object_style_response() -> None:
    class _Msg:
        content = json.dumps(VALID_PAYLOAD)

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    extractor = LLMExtractor(completion_fn=lambda **_: _Resp())
    result = extractor.extract("statement")
    assert len(result.transactions) == 2


def test_extract_strips_markdown_fences() -> None:
    fenced = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"

    def fake_completion(**_: Any) -> Any:
        return {"choices": [{"message": {"content": fenced}}]}

    extractor = LLMExtractor(completion_fn=fake_completion)
    result = extractor.extract("statement")
    assert len(result.transactions) == 2


def test_extract_recovers_from_prose_wrapper() -> None:
    noisy = "Sure! Here is the JSON:\n" + json.dumps(VALID_PAYLOAD)

    extractor = LLMExtractor(
        completion_fn=lambda **_: {
            "choices": [{"message": {"content": noisy}}]
        }
    )
    result = extractor.extract("statement")
    assert result.transactions[0].description == "Coffee Shop"


def test_extract_empty_text_raises() -> None:
    extractor = LLMExtractor(completion_fn=lambda **_: None)
    with pytest.raises(LLMExtractorError, match="empty"):
        extractor.extract("   ")


def test_extract_completion_failure_wrapped() -> None:
    def boom(**_: Any) -> Any:
        raise RuntimeError("network down")

    extractor = LLMExtractor(completion_fn=boom)
    with pytest.raises(LLMExtractorError, match="completion failed"):
        extractor.extract("statement")


def test_extract_invalid_response_shape_raises() -> None:
    extractor = LLMExtractor(
        completion_fn=lambda **_: {"unexpected": True}
    )
    with pytest.raises(LLMExtractorError, match="response shape"):
        extractor.extract("statement")


def test_extract_empty_content_raises() -> None:
    extractor = LLMExtractor(
        completion_fn=lambda **_: {
            "choices": [{"message": {"content": "   "}}]
        }
    )
    with pytest.raises(LLMExtractorError, match="empty content"):
        extractor.extract("statement")


def test_extract_invalid_json_raises() -> None:
    extractor = LLMExtractor(
        completion_fn=lambda **_: {
            "choices": [{"message": {"content": "not json"}}]
        }
    )
    with pytest.raises(LLMExtractorError, match="valid JSON"):
        extractor.extract("statement")


def test_extract_non_object_payload_raises() -> None:
    extractor = LLMExtractor(
        completion_fn=lambda **_: {
            "choices": [{"message": {"content": "[1, 2, 3]"}}]
        }
    )
    with pytest.raises(LLMExtractorError, match="object"):
        extractor.extract("statement")


def test_extract_transactions_must_be_list() -> None:
    bad = {"transactions": {"not": "a list"}}
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(bad)
    )
    with pytest.raises(LLMExtractorError, match="must be a list"):
        extractor.extract("statement")


def test_extract_transaction_item_not_object_raises() -> None:
    bad = {"transactions": ["not an object"]}
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(bad)
    )
    with pytest.raises(LLMExtractorError, match="not an object"):
        extractor.extract("statement")


def test_extract_transaction_missing_amount_raises() -> None:
    bad = {
        "transactions": [
            {"booking_date": "2026-04-01", "description": "x"}
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(bad)
    )
    with pytest.raises(LLMExtractorError, match="missing amount"):
        extractor.extract("statement")


def test_extract_invalid_amount_raises() -> None:
    bad = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "x",
                "amount": "not-a-number",
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(bad)
    )
    with pytest.raises(LLMExtractorError, match="numeric"):
        extractor.extract("statement")


def test_extract_invalid_confidence_raises() -> None:
    bad = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "x",
                "amount": 1.0,
                "confidence": "high",
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(bad)
    )
    with pytest.raises(LLMExtractorError, match="confidence"):
        extractor.extract("statement")


def test_extract_invalid_date_raises() -> None:
    bad = {
        "transactions": [
            {
                "booking_date": "not-a-date",
                "description": "x",
                "amount": 1.0,
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(bad)
    )
    with pytest.raises(LLMExtractorError, match="booking_date"):
        extractor.extract("statement")


def test_extract_invalid_balance_raises() -> None:
    bad = {
        "opening_balance": "abc",
        "transactions": [],
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(bad)
    )
    with pytest.raises(LLMExtractorError, match="numeric"):
        extractor.extract("statement")


def test_extract_default_model_from_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("BSP_HYBRID_MODEL", "anthropic/claude-3-haiku")
    captured: dict[str, Any] = {}

    extractor = LLMExtractor(
        completion_fn=lambda **kwargs: (
            captured.update(kwargs) or _fake_response(VALID_PAYLOAD)
        )
    )
    extractor.extract("statement")
    assert captured["model"] == "anthropic/claude-3-haiku"


def test_extract_populates_raw_source_text_when_description_found() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee Shop",
                "amount": -5.0,
            }
        ]
    }
    source = (
        "Statement header\n"
        "01/04/2026  CARD PAYMENT COFFEE SHOP  -5.00  495.00\n"
        "02/04/2026  SALARY                  100.00  595.00"
    )

    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    result = extractor.extract(source)
    tx = result.transactions[0]
    assert tx.raw_source_text is not None
    assert "coffee shop" in tx.raw_source_text.lower()


def test_extract_raw_source_text_none_when_no_match() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Unlisted Vendor",
                "amount": -1.0,
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    result = extractor.extract("totally unrelated text")
    assert result.transactions[0].raw_source_text is None


def test_slice_source_context_handles_edge_cases() -> None:
    from bankstatementparser.hybrid.llm_extractor import (
        _slice_source_context,
    )

    assert _slice_source_context(None, "abc") is None
    assert _slice_source_context("   ", "abc") is None
    assert _slice_source_context("abc", "") is None


def test_safe_date_handles_date_and_none() -> None:
    from datetime import date

    from bankstatementparser.hybrid.llm_extractor import _safe_date

    today = date(2026, 4, 1)
    assert _safe_date(today) is today
    assert _safe_date(None) is None
    assert _safe_date("") is None
    assert _safe_date("2026-04-01") == today


def test_extract_accepts_null_booking_date() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": None,
                "description": "no date",
                "amount": 1.0,
            }
        ],
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    result = extractor.extract("statement")
    assert result.transactions[0].booking_date is None


def test_build_messages_includes_system_and_user() -> None:
    messages = build_messages("hello")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "hello" in messages[1]["content"]


# ---------------------------------------------------------------------------
# bbox parsing (#46)
# ---------------------------------------------------------------------------


def test_extract_populates_source_bbox_when_provided() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee",
                "amount": -3.85,
                "bbox": {
                    "x0": 0.05,
                    "y0": 0.42,
                    "x1": 0.95,
                    "y1": 0.46,
                },
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    result = extractor.extract("statement")
    bbox = result.transactions[0].source_bbox
    assert bbox is not None
    assert bbox.x0 == 0.05
    assert bbox.y1 == 0.46
    assert bbox.page_index == 0


def test_extract_accepts_explicit_page_index_in_bbox() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee",
                "amount": -3.85,
                "bbox": {
                    "x0": 0.0,
                    "y0": 0.0,
                    "x1": 1.0,
                    "y1": 1.0,
                    "page_index": 2,
                },
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    result = extractor.extract("statement")
    assert result.transactions[0].source_bbox is not None
    assert result.transactions[0].source_bbox.page_index == 2


def test_extract_leaves_source_bbox_none_when_omitted() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee",
                "amount": -3.85,
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    result = extractor.extract("statement")
    assert result.transactions[0].source_bbox is None


def test_extract_leaves_source_bbox_none_when_explicitly_null() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee",
                "amount": -3.85,
                "bbox": None,
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    result = extractor.extract("statement")
    assert result.transactions[0].source_bbox is None


def test_extract_rejects_non_object_bbox() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee",
                "amount": -3.85,
                "bbox": "not-a-dict",
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    with pytest.raises(LLMExtractorError, match="non-object bbox"):
        extractor.extract("statement")


def test_extract_rejects_bbox_missing_required_keys() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee",
                "amount": -3.85,
                "bbox": {"x0": 0.1, "y0": 0.2},
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    with pytest.raises(LLMExtractorError, match="invalid bbox"):
        extractor.extract("statement")


def test_extract_rejects_inverted_bbox_x() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee",
                "amount": -3.85,
                "bbox": {"x0": 0.9, "y0": 0.2, "x1": 0.1, "y1": 0.4},
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    with pytest.raises(LLMExtractorError, match="invalid bbox"):
        extractor.extract("statement")


def test_extract_rejects_inverted_bbox_y() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee",
                "amount": -3.85,
                "bbox": {"x0": 0.1, "y0": 0.9, "x1": 0.5, "y1": 0.1},
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    with pytest.raises(LLMExtractorError, match="invalid bbox"):
        extractor.extract("statement")


def test_extract_rejects_bbox_out_of_range() -> None:
    payload = {
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Coffee",
                "amount": -3.85,
                "bbox": {"x0": 1.5, "y0": 0.2, "x1": 0.9, "y1": 0.4},
            }
        ]
    }
    extractor = LLMExtractor(
        completion_fn=lambda **_: _fake_response(payload)
    )
    with pytest.raises(LLMExtractorError, match="invalid bbox"):
        extractor.extract("statement")
