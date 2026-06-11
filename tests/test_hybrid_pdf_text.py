# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the PDF text extraction backend."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from bankstatementparser.hybrid import pdf_text
from bankstatementparser.hybrid.pdf_text import (
    PDFExtractionError,
    extract_text,
)


def test_extract_text_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PDFExtractionError, match="not found"):
        extract_text(tmp_path / "nope.pdf")


def test_extract_text_uses_pypdf_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 stub")

    class _Page:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _Reader:
        def __init__(self, _path: str) -> None:
            self.pages = [_Page("hello   world"), _Page("line two")]

    fake_module = types.ModuleType("pypdf")
    fake_module.PdfReader = _Reader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", fake_module)

    text = extract_text(pdf_path)
    assert "hello world" in text
    assert "line two" in text


def test_extract_text_handles_none_page_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    class _Page:
        def extract_text(self) -> None:
            return None

    class _Reader:
        def __init__(self, _path: str) -> None:
            self.pages = [_Page()]

    fake = types.ModuleType("pypdf")
    fake.PdfReader = _Reader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", fake)

    assert extract_text(pdf_path) == ""


def test_strip_noise_collapses_whitespace() -> None:
    assert pdf_text._strip_noise("a   b\t\tc") == "a b c"


def test_extract_text_pages_returns_per_page_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 stub")

    class _Page:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _Reader:
        def __init__(self, _path: str) -> None:
            self.pages = [_Page("hello   world"), _Page("  line two ")]

    fake_module = types.ModuleType("pypdf")
    fake_module.PdfReader = _Reader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", fake_module)

    pages = pdf_text.extract_text_pages(pdf_path)
    assert pages == ["hello world", "line two"]


def test_extract_text_pages_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PDFExtractionError, match="not found"):
        pdf_text.extract_text_pages(tmp_path / "nope.pdf")
