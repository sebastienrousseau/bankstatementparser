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

from .llm_extractor import LLMExtractor, LLMExtractorError
from .orchestrator import (
    LOW_TEXT_DENSITY_THRESHOLD,
    IngestResult,
    smart_ingest,
)
from .pdf_text import PDFExtractionError, extract_text
from .verification import (
    BalanceVerification,
    VerificationStatus,
    verify_balance,
)
from .vision import VisionExtractor, VisionExtractorError

__all__ = [
    "LOW_TEXT_DENSITY_THRESHOLD",
    "BalanceVerification",
    "IngestResult",
    "LLMExtractor",
    "LLMExtractorError",
    "PDFExtractionError",
    "VerificationStatus",
    "VisionExtractor",
    "VisionExtractorError",
    "extract_text",
    "smart_ingest",
    "verify_balance",
]
