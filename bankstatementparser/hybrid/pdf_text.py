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

"""PDF text extraction for the hybrid pipeline.

Default backend is :mod:`pypdf` (lightweight, MIT, no system deps).
``[hybrid-plus]`` users can opt-in to :mod:`pdfplumber` for higher
fidelity table extraction by passing ``engine="pdfplumber"``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Union

PathLike = Union[str, Path]
Engine = Literal["pypdf", "pdfplumber"]


class PDFExtractionError(RuntimeError):
    """Raised when PDF text extraction fails or its backend is missing."""


def _strip_noise(text: str) -> str:
    """Collapse runs of whitespace to keep LLM token usage low."""
    return re.sub(r"[ \t]+", " ", text).strip()


def extract_text(
    path: PathLike,
    *,
    engine: Engine = "pypdf",
) -> str:
    """Extract raw text from a PDF using the requested backend.

    Args:
        path: Path to the PDF file (treated as immutable).
        engine: ``"pypdf"`` (default, requires ``[hybrid]``) or
            ``"pdfplumber"`` (requires ``[hybrid-plus]``).

    Returns:
        Concatenated, whitespace-normalized text from every page.

    Raises:
        PDFExtractionError: If the backend is missing or extraction
            fails.
    """
    return "\n".join(extract_text_pages(path, engine=engine))


def extract_text_pages(
    path: PathLike,
    *,
    engine: Engine = "pypdf",
) -> list[str]:
    """Extract whitespace-normalized text from each page of a PDF.

    Keeping the per-page split (instead of one joined blob) preserves
    page provenance: the orchestrator uses it to trace each extracted
    row back to the page it came from.

    Args:
        path: Path to the PDF file (treated as immutable).
        engine: ``"pypdf"`` (default, requires ``[hybrid]``) or
            ``"pdfplumber"`` (requires ``[hybrid-plus]``).

    Returns:
        One normalized text string per page, in page order.

    Raises:
        PDFExtractionError: If the backend is missing or extraction
            fails.
    """
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise PDFExtractionError(f"PDF not found: {pdf_path}")

    if engine == "pypdf":
        pages = _extract_with_pypdf(pdf_path)
    elif engine == "pdfplumber":
        pages = _extract_with_pdfplumber(pdf_path)
    else:
        raise PDFExtractionError(f"Unknown PDF engine: {engine}")
    return [_strip_noise(page) for page in pages]


def _extract_with_pypdf(pdf_path: Path) -> list[str]:
    """Extract per-page text using the ``pypdf`` engine."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PDFExtractionError(
            "pypdf is required for PDF extraction. "
            "Install with: pip install bankstatementparser[hybrid]"
        ) from exc

    try:
        reader = PdfReader(str(pdf_path))
        return [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise PDFExtractionError(
            f"Failed to read PDF {pdf_path}: {exc}"
        ) from exc


def _extract_with_pdfplumber(
    pdf_path: Path,
) -> list[str]:
    """Extract per-page text using the ``pdfplumber`` engine."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise PDFExtractionError(
            "pdfplumber is required for engine='pdfplumber'. "
            "Install with: pip install bankstatementparser[hybrid-plus]"
        ) from exc

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:
        raise PDFExtractionError(
            f"Failed to read PDF {pdf_path}: {exc}"
        ) from exc
