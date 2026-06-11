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

"""Hybrid pipeline: deterministic parsers with LLM fallback for PDFs.

This subpackage is gated behind the ``[hybrid]`` install extra:

    pip install bankstatementparser[hybrid]

Importing :mod:`bankstatementparser.hybrid` does **not** require the
optional dependencies. Individual modules raise a clear error only when
their LLM/PDF entry points are actually invoked.
"""

from __future__ import annotations

from .evaluation import (
    EvalCase,
    EvalCaseError,
    EvalScore,
    EvalSummary,
    ExpectedTransaction,
    load_eval_case,
    load_eval_cases,
    score_extraction,
    summarize_scores,
)
from .llm_extractor import LLMExtractor, LLMExtractorError
from .ollama_direct import (
    OllamaDirectError,
    is_ollama_model,
    ollama_direct_completion,
)
from .orchestrator import (
    LOW_TEXT_DENSITY_THRESHOLD,
    IngestResult,
    smart_ingest,
)
from .pdf_text import (
    PDFExtractionError,
    extract_text,
    extract_text_pages,
)
from .scanner import FileFailure, ScanResult, scan_and_ingest
from .verification import (
    BalanceVerification,
    ContinuityBreak,
    ContinuityResult,
    VerificationStatus,
    aggregate_verifications,
    verify_balance,
    verify_balance_multi_currency,
    verify_continuity,
    verify_transactions,
)
from .vision import VisionExtractor, VisionExtractorError

__all__ = [
    "LOW_TEXT_DENSITY_THRESHOLD",
    "BalanceVerification",
    "ContinuityBreak",
    "ContinuityResult",
    "EvalCase",
    "EvalCaseError",
    "EvalScore",
    "EvalSummary",
    "ExpectedTransaction",
    "FileFailure",
    "IngestResult",
    "LLMExtractor",
    "LLMExtractorError",
    "OllamaDirectError",
    "PDFExtractionError",
    "ScanResult",
    "VerificationStatus",
    "VisionExtractor",
    "VisionExtractorError",
    "aggregate_verifications",
    "extract_text",
    "extract_text_pages",
    "is_ollama_model",
    "load_eval_case",
    "load_eval_cases",
    "ollama_direct_completion",
    "scan_and_ingest",
    "score_extraction",
    "smart_ingest",
    "summarize_scores",
    "verify_balance",
    "verify_balance_multi_currency",
    "verify_continuity",
    "verify_transactions",
]
