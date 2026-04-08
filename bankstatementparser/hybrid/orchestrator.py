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

"""Hybrid orchestrator — single entry point for the v0.0.5 pipeline.

:func:`smart_ingest` routes any input file through the cheapest viable
extraction path:

* **Path A — Deterministic.** When :func:`detect_statement_format`
  identifies an ISO/exchange format (CAMT, PAIN.001, CSV, OFX, MT940),
  the matching parser handles the file end-to-end. Free, fastest,
  byte-identical reproducible.
* **Path B — Text-LLM.** When the file is a digital PDF and
  :mod:`pypdf` extracts at least :data:`LOW_TEXT_DENSITY_THRESHOLD`
  characters of text, the orchestrator calls
  :class:`~.llm_extractor.LLMExtractor` (LiteLLM-backed, default
  ``ollama/llama3``) to parse the raw text into structured rows.
* **Path C — Vision-LLM.** When pypdf yields below-threshold text
  (i.e. the PDF is a scan, photocopy, or fax), the orchestrator
  auto-falls through to :class:`~.vision.VisionExtractor`, which
  renders pages with ``pypdfium2`` and sends base64 PNGs to a
  multimodal model. Vision is **opt-in only** via
  ``BSP_HYBRID_VISION_MODEL`` — there is no default model.

Every successful path produces an :class:`IngestResult` with
``source_method`` set to ``"deterministic"``, ``"llm"``, or
``"vision"`` so callers can audit which path produced each row.
The Golden Rule (:func:`~.verification.verify_balance`) is applied
to every result when balances are available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Optional, Union

from pydantic import ValidationError

from ..additional_parsers import create_parser, detect_statement_format
from ..transaction_models import Transaction
from .llm_extractor import LLMExtractionResult, LLMExtractor
from .pdf_text import extract_text
from .verification import BalanceVerification, verify_balance
from .vision import VisionExtractor

# A digital PDF will yield hundreds-to-thousands of characters of text.
# Anything below this is almost certainly a scanned/image-only PDF and
# should be routed to the vision model.
LOW_TEXT_DENSITY_THRESHOLD = 50

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


@dataclass(frozen=True)
class IngestResult:
    """Unified output of :func:`smart_ingest`.

    ``source_method`` is one of:

    * ``"deterministic"`` — parsed by an ISO/exchange-format parser
    * ``"llm"`` — parsed by the text-LLM fallback (digital PDF)
    * ``"vision"`` — parsed by the multimodal-LLM fallback (scan)
    """

    source_method: str
    source_format: Optional[str]
    transactions: list[Transaction]
    verification: Optional[BalanceVerification] = None
    warnings: list[str] = field(default_factory=list)


def smart_ingest(
    path: PathLike,
    *,
    extractor: Optional[LLMExtractor] = None,
    vision_extractor: Optional[VisionExtractor] = None,
    opening_balance: Optional[Decimal] = None,
    closing_balance: Optional[Decimal] = None,
) -> IngestResult:
    """Route a statement file through the right extraction path.

    The pipeline tries three paths in order:

    1. **Deterministic** — ISO/exchange-format parser (free, fastest).
    2. **Text-LLM** — for digital PDFs where pypdf yields usable text.
    3. **Vision-LLM** — for scanned/image-only PDFs (length below
       :data:`LOW_TEXT_DENSITY_THRESHOLD`). Requires
       ``BSP_HYBRID_VISION_MODEL`` to be set.

    Args:
        path: Statement file path. Treated as immutable.
        extractor: Pre-configured text :class:`LLMExtractor`. Created
            lazily on demand.
        vision_extractor: Pre-configured :class:`VisionExtractor` for
            scanned PDFs. Created lazily on demand.
        opening_balance: Optional verification override.
        closing_balance: Optional verification override.

    Returns:
        An :class:`IngestResult` tagged with ``source_method`` so the
        caller can audit which path produced each row.
    """
    file_path = Path(path)
    warnings: list[str] = []

    fmt = _safe_detect(file_path, warnings)
    if fmt and fmt.lower() != "pdf":
        try:
            return _run_deterministic(
                file_path,
                fmt,
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                warnings=warnings,
            )
        except Exception as exc:
            logger.warning(
                "Deterministic parse failed for %s (%s): %s",
                file_path,
                fmt,
                exc,
            )
            warnings.append(
                f"Deterministic parser '{fmt}' failed: {exc}"
            )

    return _run_pdf_fallbacks(
        file_path,
        extractor=extractor,
        vision_extractor=vision_extractor,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        warnings=warnings,
    )


def _safe_detect(
    file_path: Path, warnings: list[str]
) -> Optional[str]:
    try:
        return detect_statement_format(str(file_path))
    except Exception as exc:
        warnings.append(f"Format detection failed: {exc}")
        return None


def _run_deterministic(
    file_path: Path,
    fmt: str,
    *,
    opening_balance: Optional[Decimal],
    closing_balance: Optional[Decimal],
    warnings: list[str],
) -> IngestResult:
    parser = create_parser(str(file_path), fmt)
    raw = parser.parse()
    transactions = _coerce_transactions(raw, source=fmt)
    verification = (
        verify_balance(
            transactions,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
        )
        if opening_balance is not None and closing_balance is not None
        else None
    )
    return IngestResult(
        source_method="deterministic",
        source_format=fmt,
        transactions=transactions,
        verification=verification,
        warnings=warnings,
    )


def _run_pdf_fallbacks(
    file_path: Path,
    *,
    extractor: Optional[LLMExtractor],
    vision_extractor: Optional[VisionExtractor],
    opening_balance: Optional[Decimal],
    closing_balance: Optional[Decimal],
    warnings: list[str],
) -> IngestResult:
    """Path B (text-LLM) → Path C (vision-LLM) routing for PDFs."""
    text = extract_text(file_path)
    stripped_len = len(text.strip())

    if stripped_len < LOW_TEXT_DENSITY_THRESHOLD:
        warnings.append(
            f"LOW_TEXT_DENSITY: extracted {stripped_len} chars "
            f"(threshold {LOW_TEXT_DENSITY_THRESHOLD}). "
            "Routing to vision model."
        )
        logger.warning(
            "Low text density for %s; routing to vision path",
            file_path,
        )
        return _run_vision(
            file_path,
            vision_extractor=vision_extractor,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            warnings=warnings,
        )

    extractor = extractor or LLMExtractor()
    result = extractor.extract(text)
    return _build_ingest_result(
        source_method="llm",
        result=result,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        warnings=warnings,
    )


def _run_vision(
    file_path: Path,
    *,
    vision_extractor: Optional[VisionExtractor],
    opening_balance: Optional[Decimal],
    closing_balance: Optional[Decimal],
    warnings: list[str],
) -> IngestResult:
    vision_extractor = vision_extractor or VisionExtractor()
    result = vision_extractor.extract(file_path)
    return _build_ingest_result(
        source_method="vision",
        result=result,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        warnings=warnings,
    )


def _build_ingest_result(
    *,
    source_method: str,
    result: LLMExtractionResult,
    opening_balance: Optional[Decimal],
    closing_balance: Optional[Decimal],
    warnings: list[str],
) -> IngestResult:
    effective_opening = (
        opening_balance
        if opening_balance is not None
        else result.opening_balance
    )
    effective_closing = (
        closing_balance
        if closing_balance is not None
        else result.closing_balance
    )

    verification = verify_balance(
        result.transactions,
        opening_balance=effective_opening,
        closing_balance=effective_closing,
    )

    return IngestResult(
        source_method=source_method,
        source_format="pdf",
        transactions=result.transactions,
        verification=verification,
        warnings=warnings,
    )


def _coerce_transactions(
    raw: object, *, source: str
) -> list[Transaction]:
    """Normalize parser output (DataFrame / list / dict) to Transactions."""
    if raw is None:
        return []

    records: list[dict[str, object]]
    to_dict = getattr(raw, "to_dict", None)
    if callable(to_dict):
        try:
            records = list(to_dict("records"))
        except TypeError:  # pragma: no cover - non-DataFrame fallback
            records = []
    elif isinstance(raw, list):
        records = [dict(item) for item in raw if isinstance(item, dict)]
    elif isinstance(raw, dict):
        records = [dict(raw)]
    else:  # pragma: no cover - defensive
        records = []

    transactions: list[Transaction] = []
    for index, record in enumerate(records):
        try:
            transactions.append(
                Transaction.from_record(
                    record,
                    source=source,
                    source_index=index,
                )
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            DecimalException,
            ValidationError,
        ) as exc:
            # Summary rows, empty rows, and malformed entries don't
            # satisfy `Transaction.from_record`'s amount requirement.
            # They are expected and safely skipped.
            logger.debug(
                "Skipping record %d (%s): %s",
                index,
                source,
                exc,
            )
    return transactions
