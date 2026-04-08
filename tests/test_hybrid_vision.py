# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the multimodal vision extractor."""

from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from bankstatementparser.hybrid import vision as vision_mod
from bankstatementparser.hybrid.vision import (
    VisionExtractor,
    VisionExtractorError,
    _build_vision_messages,
)

# ---------------------------------------------------------------------------
# Fake pypdfium2 module so tests don't require the real wheel
# ---------------------------------------------------------------------------


class _FakeBitmap:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def to_pil(self) -> Any:
        bitmap = self

        class _PilLike:
            def save(self, buffer: Any, format: str) -> None:  # noqa: A002
                assert format == "PNG"
                buffer.write(bitmap._payload)

        return _PilLike()


class _FakePage:
    def __init__(self, payload: bytes, *, fail: bool = False) -> None:
        self._payload = payload
        self._fail = fail

    def render(self, scale: float) -> _FakeBitmap:
        if self._fail:
            raise RuntimeError("render boom")
        return _FakeBitmap(self._payload)


class _FakePdfDocument:
    def __init__(self, pages: list[_FakePage]) -> None:
        self._pages = pages

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, index: int) -> _FakePage:
        return self._pages[index]


def _install_fake_pdfium(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[_FakePage] | None = None,
    *,
    open_fail: bool = False,
) -> None:
    module = types.ModuleType("pypdfium2")
    effective = (
        pages if pages is not None else [_FakePage(b"PNGBYTES_PAGE_1")]
    )

    def _doc_factory(_path: str) -> _FakePdfDocument:
        if open_fail:
            raise RuntimeError("cannot open")
        return _FakePdfDocument(effective)

    module.PdfDocument = _doc_factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdfium2", module)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _valid_vision_payload() -> dict[str, Any]:
    return {
        "account_id": "GB1",
        "currency": "GBP",
        "opening_balance": "100.00",
        "closing_balance": "70.00",
        "transactions": [
            {
                "booking_date": "2026-04-01",
                "description": "Scanned Coffee",
                "amount": -30.00,
                "reference": None,
                "confidence": 0.82,
            }
        ],
    }


def test_vision_extract_renders_and_calls_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF stub")
    _install_fake_pdfium(
        monkeypatch,
        [
            _FakePage(b"PAGE1"),
            _FakePage(b"PAGE2"),
        ],
    )

    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_valid_vision_payload())
                    }
                }
            ]
        }

    extractor = VisionExtractor(
        model="ollama/llava",
        completion_fn=fake_completion,
    )
    result = extractor.extract(pdf_path)

    assert captured["model"] == "ollama/llava"
    assert captured["temperature"] == 0.0
    messages = captured["messages"]
    # system + user(multimodal)
    assert len(messages) == 2
    user_content = messages[1]["content"]
    # 1 text part + 2 image parts
    assert len(user_content) == 3
    assert user_content[0]["type"] == "text"
    assert user_content[1]["type"] == "image_url"
    # base64-encoded page bytes
    b64 = base64.b64encode(b"PAGE1").decode("ascii")
    assert b64 in user_content[1]["image_url"]["url"]

    assert len(result.transactions) == 1
    assert result.transactions[0].description == "Scanned Coffee"


def test_vision_extract_caps_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF stub")
    pages = [_FakePage(f"P{i}".encode()) for i in range(20)]
    _install_fake_pdfium(monkeypatch, pages)

    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_valid_vision_payload())
                    }
                }
            ]
        }

    VisionExtractor(
        model="ollama/llava",
        completion_fn=fake_completion,
        max_pages=3,
    ).extract(pdf_path)

    user_content = captured["messages"][1]["content"]
    # 1 text + 3 images (capped)
    assert len(user_content) == 4


def test_vision_requires_configured_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF stub")
    monkeypatch.delenv("BSP_HYBRID_VISION_MODEL", raising=False)

    extractor = VisionExtractor(completion_fn=lambda **_: None)
    with pytest.raises(VisionExtractorError, match="Vision model required"):
        extractor.extract(pdf_path)


def test_vision_reads_model_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF stub")
    monkeypatch.setenv("BSP_HYBRID_VISION_MODEL", "gpt-4o")
    _install_fake_pdfium(monkeypatch)

    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_valid_vision_payload())
                    }
                }
            ]
        }

    VisionExtractor(completion_fn=fake_completion).extract(pdf_path)
    assert captured["model"] == "gpt-4o"


def test_vision_passes_api_base_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF stub")
    _install_fake_pdfium(monkeypatch)

    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_valid_vision_payload())
                    }
                }
            ]
        }

    VisionExtractor(
        model="ollama/llava",
        api_base="http://localhost:11434",
        completion_fn=fake_completion,
    ).extract(pdf_path)
    assert captured["api_base"] == "http://localhost:11434"


def test_vision_completion_failure_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF stub")
    _install_fake_pdfium(monkeypatch)

    def boom(**_: Any) -> Any:
        raise RuntimeError("network")

    extractor = VisionExtractor(
        model="ollama/llava", completion_fn=boom
    )
    with pytest.raises(VisionExtractorError, match="Vision completion"):
        extractor.extract(pdf_path)


def test_vision_open_pdf_failure_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF stub")
    _install_fake_pdfium(monkeypatch, open_fail=True)

    extractor = VisionExtractor(
        model="ollama/llava", completion_fn=lambda **_: None
    )
    with pytest.raises(VisionExtractorError, match="Failed to open"):
        extractor.extract(pdf_path)


def test_vision_render_failure_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF stub")
    _install_fake_pdfium(
        monkeypatch, [_FakePage(b"", fail=True)]
    )

    extractor = VisionExtractor(
        model="ollama/llava", completion_fn=lambda **_: None
    )
    with pytest.raises(VisionExtractorError, match="render page 0"):
        extractor.extract(pdf_path)


def test_vision_empty_render_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF stub")
    _install_fake_pdfium(monkeypatch, [])

    extractor = VisionExtractor(
        model="ollama/llava", completion_fn=lambda **_: None
    )
    with pytest.raises(VisionExtractorError, match="No pages rendered"):
        extractor.extract(pdf_path)


def test_is_configured_reflects_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BSP_HYBRID_VISION_MODEL", raising=False)
    assert VisionExtractor.is_configured() is False
    monkeypatch.setenv("BSP_HYBRID_VISION_MODEL", "gpt-4o")
    assert VisionExtractor.is_configured() is True


def test_build_vision_messages_encodes_images() -> None:
    messages = _build_vision_messages([b"A", b"B"])
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    content = messages[1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert len(content) == 3  # 1 text + 2 images


def test_vision_module_exports_error_subclass() -> None:
    assert issubclass(
        vision_mod.VisionExtractorError,
        vision_mod.LLMExtractorError,
    )
