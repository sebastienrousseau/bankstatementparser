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

"""Multimodal vision fallback for image-only / scanned PDFs.

Used by :mod:`bankstatementparser.hybrid.orchestrator` as Path C when
text extraction yields too few characters to be a digital PDF.

Pages are rendered with :mod:`pypdfium2` (pure-Python wheel, no system
dependencies — chosen over ``pdf2image``/poppler for WSL/macOS/Linux
parity) and sent to a multimodal LLM via LiteLLM's OpenAI-compatible
``image_url`` payload.

The vision model is **never** chosen for the user. They must explicitly
set :data:`ENV_VISION_MODEL` (``BSP_HYBRID_VISION_MODEL``) — vision
inference is resource-heavy and can incur real cost.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Union

from .llm_extractor import (
    LLMExtractionResult,
    LLMExtractorError,
    _build_result,
    _extract_message_content,
    _parse_json_payload,
)

PathLike = Union[str, Path]
CompletionFn = Callable[..., Any]

ENV_VISION_MODEL = "BSP_HYBRID_VISION_MODEL"
ENV_API_BASE = "BSP_HYBRID_API_BASE"

# Render scale factor: 2.0 ≈ 144 DPI, a sweet spot between OCR
# legibility and base64 payload size for the LLM call.
DEFAULT_RENDER_SCALE = 2.0

VISION_SYSTEM_PROMPT = """You are a meticulous Financial Data Architect.
You receive one or more IMAGES of a bank statement (scanned PDF or
photo). Read the spatial layout — columns, headers, row alignment —
and extract every transaction. Never invent values. If a field is
unclear, return null. Output ONLY a single JSON object — no prose, no
markdown.

After identifying transactions, SORT them chronologically by
booking_date (oldest first). When two rows share a date, preserve the
visual top-to-bottom order so opening/closing balance arithmetic
remains consistent.

For each transaction row, also return its bounding box on the page
as four NORMALIZED coordinates in the 0.0-1.0 range. ``x0,y0`` is
the top-left of the row, ``x1,y1`` is the bottom-right. Origin is
the top-left of the image. The bbox lets a downstream review UI
highlight the exact pixels each row was extracted from. If you
truly cannot estimate the bbox for a row, return ``null`` for the
bbox field on that row only — do not skip the transaction.

Schema:
{
  "account_id": string|null,
  "currency": string|null,
  "opening_balance": number|null,
  "closing_balance": number|null,
  "transactions": [
    {
      "booking_date": "YYYY-MM-DD",
      "description": string,
      "amount": number,
      "reference": string|null,
      "confidence": number,
      "bbox": {"x0": number, "y0": number, "x1": number, "y1": number}|null
    }
  ]
}
"""

VISION_USER_PROMPT = (
    "Extract every transaction from the attached image(s) of this "
    "bank statement. Preserve sign convention (debits negative, "
    "credits positive). Return JSON only."
)


class VisionExtractorError(LLMExtractorError):
    """Raised when the vision pipeline cannot complete."""


class VisionExtractor:
    """Render PDF pages and extract transactions via a multimodal LLM.

    Args:
        model: LiteLLM-style multimodal model id (e.g. ``ollama/llava``
            or ``gpt-4o``). Defaults to ``BSP_HYBRID_VISION_MODEL`` env
            var. **No fallback default** — vision inference is opt-in.
        api_base: Optional API base for self-hosted endpoints.
        completion_fn: Injectable completion callable for testing.
        render_scale: pypdfium2 render scale (default ``2.0`` ≈ 144 DPI).
        max_pages: Hard cap on pages sent to the model to keep token
            usage bounded. Defaults to ``5``.
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
        completion_fn: Optional[CompletionFn] = None,
        render_scale: float = DEFAULT_RENDER_SCALE,
        max_pages: int = 5,
    ) -> None:
        self.model = model or os.environ.get(ENV_VISION_MODEL)
        self.api_base = api_base or os.environ.get(ENV_API_BASE)
        self._completion_fn = completion_fn
        self.render_scale = render_scale
        self.max_pages = max_pages

    @classmethod
    def is_configured(cls) -> bool:
        """Return ``True`` when a vision model is set in the env."""
        return bool(os.environ.get(ENV_VISION_MODEL))

    def extract(self, pdf_path: PathLike) -> LLMExtractionResult:
        """Render the PDF and run the multimodal extraction call."""
        if not self.model:
            raise VisionExtractorError(
                "PDF appears to be a scan. Vision model required for "
                "processing. Set BSP_HYBRID_VISION_MODEL to continue "
                "(e.g. 'ollama/llava' or 'gpt-4o')."
            )

        images = self._render_pages(Path(pdf_path))
        if not images:
            raise VisionExtractorError(
                f"No pages rendered from {pdf_path}"
            )

        completion = self._resolve_completion()
        messages = _build_vision_messages(images)

        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.0,
            }
            if self.api_base:
                kwargs["api_base"] = self.api_base
            response = completion(**kwargs)
        except Exception as exc:
            raise VisionExtractorError(
                f"Vision completion failed: {exc}"
            ) from exc

        raw = _extract_message_content(response)
        payload = _parse_json_payload(raw)
        return _build_result(payload, raw, source_text="")

    def _render_pages(self, pdf_path: Path) -> list[bytes]:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:  # pragma: no cover - optional dep
            raise VisionExtractorError(
                "pypdfium2 is required for vision extraction. "
                "Install with: "
                "pip install bankstatementparser[hybrid-vision]"
            ) from exc

        try:
            pdf = pdfium.PdfDocument(str(pdf_path))
        except Exception as exc:
            raise VisionExtractorError(
                f"Failed to open PDF {pdf_path}: {exc}"
            ) from exc

        rendered: list[bytes] = []
        page_count = min(len(pdf), self.max_pages)
        for page_index in range(page_count):
            page = pdf[page_index]
            try:
                bitmap = page.render(scale=self.render_scale)
                pil_image = bitmap.to_pil()
                buffer = BytesIO()
                pil_image.save(buffer, format="PNG")
                rendered.append(buffer.getvalue())
            except Exception as exc:
                raise VisionExtractorError(
                    f"Failed to render page {page_index}: {exc}"
                ) from exc
        return rendered

    def _resolve_completion(self) -> CompletionFn:
        if self._completion_fn is not None:
            return self._completion_fn
        try:  # pragma: no cover - optional dep
            from litellm import completion
        except ImportError as exc:  # pragma: no cover - optional dep
            raise VisionExtractorError(
                "litellm is required for vision extraction. "
                "Install with: "
                "pip install bankstatementparser[hybrid-vision]"
            ) from exc
        return completion  # type: ignore[no-any-return]  # pragma: no cover


def _build_vision_messages(
    images: list[bytes],
) -> list[dict[str, Any]]:
    """Build OpenAI/LiteLLM-style multimodal messages."""
    content: list[dict[str, Any]] = [
        {"type": "text", "text": VISION_USER_PROMPT}
    ]
    for png_bytes in images:
        b64 = base64.b64encode(png_bytes).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                },
            }
        )
    return [
        {"role": "system", "content": VISION_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
