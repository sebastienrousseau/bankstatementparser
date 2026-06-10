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
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Union

from .._llm_common import (
    ENV_API_BASE,
    ENV_VISION_MODEL,
    warn_if_data_leaves_machine,
)
from ..transaction_models import Transaction
from .llm_extractor import (
    LLMExtractionResult,
    LLMExtractorError,
    _build_result,
    _extract_message_content,
    _parse_json_payload,
)

PathLike = Union[str, Path]
CompletionFn = Callable[..., Any]

# Render scale factor: 2.0 ≈ 144 DPI, a sweet spot between OCR
# legibility and base64 payload size for the LLM call.
DEFAULT_RENDER_SCALE = 2.0

# Number of horizontal strips per page when ``strip_rows=True``.
# 4 strips on a typical UK bank statement (1 header band, 2 body
# bands, 1 footer band) is enough to keep each strip below
# CLIP's effective resolution while still bounding LLM call count.
DEFAULT_STRIP_COUNT = 4

# Strips overlap by this fraction of strip height. 0.10 = 10% so
# any transaction row that bisects a boundary is seen by both
# adjacent strips. Duplicates are removed at merge time via
# ``Transaction.transaction_hash``.
STRIP_OVERLAP_FRACTION = 0.10

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
      "value_date": "YYYY-MM-DD"|null,
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
        model: LiteLLM-style multimodal model id (e.g.
            ``ollama/minicpm-v`` or ``gpt-4o``). Defaults to
            ``BSP_HYBRID_VISION_MODEL`` env var. **No fallback
            default** — vision inference is opt-in.
        api_base: Optional API base for self-hosted endpoints.
        completion_fn: Injectable completion callable for testing.
            When ``None`` and ``model`` starts with ``ollama/``, the
            extractor auto-selects
            :func:`~.ollama_direct.ollama_direct_completion` to
            sidestep the upstream LiteLLM hang on long vision prompts.
        render_scale: pypdfium2 render scale (default ``2.0`` ≈ 144
            DPI).
        max_pages: Hard cap on pages sent to the model to keep token
            usage bounded. Defaults to ``5``.
        strip_rows: When ``True``, split each page into horizontal
            strips and run one LLM call per strip instead of one
            call per page. Trades a few extra LLM calls for
            substantially better accuracy because the vision model's
            CLIP encoder receives a 336×336 image of a smaller
            region instead of a 336×336 squash of the whole page —
            crucial for small local models like ``minicpm-v:8b`` and
            ``qwen2-vl:7b``. Hosted models like ``gpt-4o`` work fine
            with the default single-shot path. See
            :data:`DEFAULT_STRIP_COUNT`.
        n_strips: Number of horizontal strips per page when
            ``strip_rows=True``. Default ``DEFAULT_STRIP_COUNT``
            (4) — first strip contains header + opening balance,
            last strip contains footer + closing balance, middle
            strips contain transaction rows. Strips overlap by
            :data:`STRIP_OVERLAP_FRACTION` (10%) so rows that
            bisect a boundary are seen by both strips and dedup'd
            on the merge step via ``transaction_hash``.
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
        completion_fn: Optional[CompletionFn] = None,
        render_scale: float = DEFAULT_RENDER_SCALE,
        max_pages: int = 5,
        strip_rows: bool = False,
        n_strips: int = DEFAULT_STRIP_COUNT,
    ) -> None:
        self.model = model or os.environ.get(ENV_VISION_MODEL)
        self.api_base = api_base or os.environ.get(ENV_API_BASE)
        self._completion_fn = completion_fn
        warn_if_data_leaves_machine(self.model, self.api_base)
        self.render_scale = render_scale
        self.max_pages = max_pages
        self.strip_rows = strip_rows
        if n_strips < 2:
            raise ValueError("n_strips must be at least 2")
        self.n_strips = n_strips

    @classmethod
    def is_configured(cls) -> bool:
        """Return ``True`` when a vision model is set in the env."""
        return bool(os.environ.get(ENV_VISION_MODEL))

    def extract(self, pdf_path: PathLike) -> LLMExtractionResult:
        """Render the PDF and run the multimodal extraction call.

        When :attr:`strip_rows` is ``False`` (default), the entire
        first page is sent in one call — fastest, fine for hosted
        models like ``gpt-4o``. When ``strip_rows`` is ``True``,
        the page is split into :attr:`n_strips` overlapping
        horizontal strips and one LLM call runs per strip; results
        are merged via :class:`Transaction.transaction_hash`. The
        strip path is dramatically more accurate for small local
        models (``ollama/minicpm-v``, ``ollama/qwen2-vl``) because
        each call sees a smaller region of the page before CLIP's
        336×336 downsample destroys fine table detail.
        """
        if not self.model:
            raise VisionExtractorError(
                "PDF appears to be a scan. Vision model required for "
                "processing. Set BSP_HYBRID_VISION_MODEL to continue "
                "(e.g. 'ollama/minicpm-v' or 'gpt-4o')."
            )

        if self.strip_rows:
            return self._extract_strip(Path(pdf_path))

        images = self._render_pages(Path(pdf_path))
        if not images:
            raise VisionExtractorError(
                f"No pages rendered from {pdf_path}"
            )

        return self._call_vision(_build_vision_messages(images))

    def _call_vision(
        self,
        messages: list[dict[str, Any]],
    ) -> LLMExtractionResult:
        """Run a single multimodal completion call and parse the result."""
        completion = self._resolve_completion()
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

    def _extract_strip(self, pdf_path: Path) -> LLMExtractionResult:
        """Strip-mode extraction: per-strip LLM calls + merge by hash.

        Renders each page into :attr:`n_strips` overlapping
        horizontal strips. Strip 0 (top) gets a "header" prompt
        that asks for account_id, currency, opening_balance, and
        closing_balance — the page header and the running-balance
        column at the right are usually visible in the top strip.
        Subsequent strips get a "body" prompt that asks only for
        transactions. Results are merged by ``transaction_hash``;
        balances from the header strip win.
        """
        page_strips = self._render_strips(pdf_path)
        if not page_strips:
            raise VisionExtractorError(
                f"No strips rendered from {pdf_path}"
            )

        merged_transactions: list[Transaction] = []
        seen_hashes: set[str] = set()
        account_id: Optional[str] = None
        currency: Optional[str] = None
        opening_balance: Optional[Decimal] = None
        closing_balance: Optional[Decimal] = None
        raw_responses: list[str] = []

        for strip_index, strip_bytes in enumerate(page_strips):
            is_header = strip_index == 0
            messages = _build_strip_messages(
                strip_bytes,
                strip_index=strip_index,
                total_strips=len(page_strips),
                include_balances=is_header,
            )
            partial = self._call_vision(messages)
            raw_responses.append(partial.raw_response)

            if is_header:
                account_id = partial.account_id or account_id
                currency = partial.currency or currency
                opening_balance = (
                    partial.opening_balance
                    if partial.opening_balance is not None
                    else opening_balance
                )
                closing_balance = (
                    partial.closing_balance
                    if partial.closing_balance is not None
                    else closing_balance
                )

            for tx in partial.transactions:
                digest = tx.transaction_hash
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                merged_transactions.append(tx)

        return LLMExtractionResult(
            account_id=account_id,
            currency=currency,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            transactions=merged_transactions,
            raw_response="\n--- strip break ---\n".join(raw_responses),
        )

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

    def _render_strips(self, pdf_path: Path) -> list[bytes]:
        """Render every page as :attr:`n_strips` overlapping PNG strips.

        Returns a flat list across all pages: page 0 strips first,
        then page 1 strips, etc. Each strip is encoded as a
        standalone PNG and ready to feed into a multimodal LLM
        call. Strips overlap by :data:`STRIP_OVERLAP_FRACTION` so
        rows that bisect a boundary are seen by both adjacent
        strips and dedup'd by ``transaction_hash`` at merge time.
        """
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

        all_strips: list[bytes] = []
        page_count = min(len(pdf), self.max_pages)
        for page_index in range(page_count):
            page = pdf[page_index]
            try:
                bitmap = page.render(scale=self.render_scale)
                pil_image = bitmap.to_pil()
            except Exception as exc:
                raise VisionExtractorError(
                    f"Failed to render page {page_index}: {exc}"
                ) from exc

            width, height = pil_image.size
            strip_height = height // self.n_strips
            overlap = int(strip_height * STRIP_OVERLAP_FRACTION)

            for strip_index in range(self.n_strips):
                top = max(0, strip_index * strip_height - overlap)
                bottom = min(
                    height,
                    (strip_index + 1) * strip_height + overlap,
                )
                try:
                    strip_image = pil_image.crop((0, top, width, bottom))
                    buffer = BytesIO()
                    strip_image.save(buffer, format="PNG")
                    all_strips.append(buffer.getvalue())
                except Exception as exc:
                    raise VisionExtractorError(
                        f"Failed to render strip {strip_index} of "
                        f"page {page_index}: {exc}"
                    ) from exc
        return all_strips

    def _resolve_completion(self) -> CompletionFn:
        if self._completion_fn is not None:
            return self._completion_fn
        # Auto-select the direct Ollama bridge for any ollama/* model
        # to sidestep the upstream LiteLLM ↔ Ollama hang on long
        # vision system prompts. See `ollama_direct.py` for the full
        # rationale and the v0.0.5 smoke-test evidence that motivated
        # this default.
        from .ollama_direct import (
            is_ollama_model,
            ollama_direct_completion,
        )

        if is_ollama_model(self.model):
            return ollama_direct_completion
        try:  # pragma: no cover - optional dep
            from litellm import completion
        except ImportError as exc:  # pragma: no cover - optional dep
            raise VisionExtractorError(
                "litellm is required for vision extraction. "
                "Install with: "
                "pip install bankstatementparser[hybrid-vision]"
            ) from exc
        return completion  # type: ignore[no-any-return]  # pragma: no cover


STRIP_HEADER_SYSTEM_PROMPT = """You are a meticulous Financial Data
Architect. You receive an IMAGE of the TOP STRIP of a bank statement
page (header band). Extract the account metadata and the running
balances if visible. Then list every transaction row that appears
in this strip. Output ONLY a single JSON object — no prose, no
markdown — using this schema:

{
  "account_id": string|null,
  "currency": string|null,
  "opening_balance": number|null,
  "closing_balance": number|null,
  "transactions": [
    {
      "booking_date": "YYYY-MM-DD",
      "value_date": "YYYY-MM-DD"|null,
      "description": string,
      "amount": number,
      "reference": string|null,
      "confidence": number
    }
  ]
}

Sign convention: debits negative, credits positive. If a field is
unclear, return null. If no transactions are visible in this
strip, return an empty transactions array.
"""

STRIP_BODY_SYSTEM_PROMPT = """You are a meticulous Financial Data
Architect. You receive an IMAGE of a HORIZONTAL BAND from the
middle of a bank statement page. Extract every transaction row
visible in this band. Output ONLY a single JSON object — no prose,
no markdown — using this schema:

{
  "transactions": [
    {
      "booking_date": "YYYY-MM-DD",
      "value_date": "YYYY-MM-DD"|null,
      "description": string,
      "amount": number,
      "reference": string|null,
      "confidence": number
    }
  ]
}

Sign convention: debits negative, credits positive. Do NOT
fabricate the account header or balances — those are extracted
from a separate strip. If a field is unclear, return null. If no
transactions are visible in this band, return an empty array.
Sort the rows you can see chronologically by booking_date.
"""


def _build_strip_messages(
    strip_image: bytes,
    *,
    strip_index: int,
    total_strips: int,
    include_balances: bool,
) -> list[dict[str, Any]]:
    """Build messages for a single strip-mode LLM call.

    The system prompt differs between the header strip (strip 0,
    asks for balances + transactions) and body strips (asks for
    transactions only) so the model isn't tempted to hallucinate
    a balance that's only visible in the header band.
    """
    system_prompt = (
        STRIP_HEADER_SYSTEM_PROMPT
        if include_balances
        else STRIP_BODY_SYSTEM_PROMPT
    )
    user_text = (
        f"This is strip {strip_index + 1} of {total_strips} from a "
        f"bank statement page. Extract every transaction visible in "
        f"this band. Return JSON only."
    )
    b64 = base64.b64encode(strip_image).decode("ascii")
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{b64}",
                    },
                },
            ],
        },
    ]


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
