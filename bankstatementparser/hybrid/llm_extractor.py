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

"""LiteLLM-backed transaction extractor.

LiteLLM provides a single OpenAI-style call surface that routes to
Ollama (default), Anthropic, OpenAI, etc. via the ``model`` argument
or the ``BSP_HYBRID_MODEL`` environment variable.

Examples:
    >>> import os
    >>> os.environ["BSP_HYBRID_MODEL"] = "ollama/llama3"  # default
    >>> extractor = LLMExtractor()
    >>> result = extractor.extract(statement_text)
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from ..transaction_models import Transaction, normalize_description
from .prompts import build_messages

DEFAULT_MODEL = "ollama/llama3"
ENV_MODEL = "BSP_HYBRID_MODEL"
ENV_API_BASE = "BSP_HYBRID_API_BASE"

CompletionFn = Callable[..., Any]

# How many characters of context to capture around a matched
# description in the source text. Tuned to fit a single statement row
# without bloating the model.
RAW_CONTEXT_RADIUS = 80


class LLMExtractorError(RuntimeError):
    """Raised when the LLM extraction call or its parsing fails."""


@dataclass(frozen=True)
class LLMExtractionResult:
    """Structured output of an LLM extraction call."""

    account_id: Optional[str]
    currency: Optional[str]
    opening_balance: Optional[Decimal]
    closing_balance: Optional[Decimal]
    transactions: list[Transaction]
    raw_response: str


class LLMExtractor:
    """Extract transactions from raw statement text via an LLM.

    Args:
        model: LiteLLM model id. Defaults to ``BSP_HYBRID_MODEL`` env
            var, then to ``ollama/llama3`` (local, private).
        api_base: Optional API base for self-hosted endpoints (e.g.
            ``http://localhost:11434`` for Ollama). Reads
            ``BSP_HYBRID_API_BASE`` if not provided.
        completion_fn: Injectable completion callable for testing. If
            ``None``, the real :func:`litellm.completion` is used at
            call time (lazy import).
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
        completion_fn: Optional[CompletionFn] = None,
    ) -> None:
        self.model = model or os.environ.get(ENV_MODEL, DEFAULT_MODEL)
        self.api_base = api_base or os.environ.get(ENV_API_BASE)
        self._completion_fn = completion_fn

    def extract(self, statement_text: str) -> LLMExtractionResult:
        """Run the LLM and parse the structured response."""
        if not statement_text.strip():
            raise LLMExtractorError("Statement text is empty")

        completion = self._resolve_completion()
        messages = build_messages(statement_text)

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
            raise LLMExtractorError(
                f"LLM completion failed: {exc}"
            ) from exc

        raw = _extract_message_content(response)
        payload = _parse_json_payload(raw)
        return _build_result(payload, raw, source_text=statement_text)

    def _resolve_completion(self) -> CompletionFn:
        if self._completion_fn is not None:
            return self._completion_fn
        try:  # pragma: no cover - optional dep
            from litellm import completion
        except ImportError as exc:  # pragma: no cover - optional dep
            raise LLMExtractorError(
                "litellm is required for LLM extraction. "
                "Install with: pip install bankstatementparser[hybrid]"
            ) from exc
        return completion  # type: ignore[no-any-return]  # pragma: no cover


def _extract_message_content(response: Any) -> str:
    """Pull the assistant message content out of an OpenAI-style response."""
    try:
        if isinstance(response, dict):
            choice = response["choices"][0]
            message = choice["message"]
            content = message["content"]
        else:
            content = response.choices[0].message.content
    except (AttributeError, KeyError, IndexError, TypeError) as exc:
        raise LLMExtractorError(
            f"Unexpected LLM response shape: {exc}"
        ) from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMExtractorError("LLM returned empty content")
    return content


_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL
)


def _parse_json_payload(raw: str) -> dict[str, Any]:
    """Tolerantly parse a JSON object from a model response."""
    text = raw.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMExtractorError(
            f"LLM did not return valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise LLMExtractorError(
            "LLM JSON payload must be an object"
        )
    return payload


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise LLMExtractorError(
            f"Invalid numeric value from LLM: {value!r}"
        ) from exc


def _slice_source_context(
    description: Optional[str], source_text: str
) -> Optional[str]:
    """Best-effort substring lookup for v0.0.6 review mode.

    The LLM doesn't tell us which characters became which row, so we
    do a case-insensitive search for the description and return a
    window around the first hit. Returns ``None`` when no match is
    found — review mode will then surface the full statement text.
    """
    if not description or not source_text:
        return None
    needle = description.strip().lower()
    if not needle:
        return None
    haystack = source_text.lower()
    idx = haystack.find(needle)
    if idx == -1:
        return None
    start = max(0, idx - RAW_CONTEXT_RADIUS)
    end = min(len(source_text), idx + len(needle) + RAW_CONTEXT_RADIUS)
    return source_text[start:end].strip()


def _build_result(
    payload: dict[str, Any], raw: str, *, source_text: str = ""
) -> LLMExtractionResult:
    raw_txs = payload.get("transactions") or []
    if not isinstance(raw_txs, list):
        raise LLMExtractorError(
            "LLM 'transactions' field must be a list"
        )

    account_id = payload.get("account_id")
    currency = payload.get("currency")
    opening = _to_decimal(payload.get("opening_balance"))
    closing = _to_decimal(payload.get("closing_balance"))

    transactions: list[Transaction] = []
    for index, item in enumerate(raw_txs):
        if not isinstance(item, dict):
            raise LLMExtractorError(
                f"Transaction at index {index} is not an object"
            )
        amount = _to_decimal(item.get("amount"))
        if amount is None:
            raise LLMExtractorError(
                f"Transaction at index {index} missing amount"
            )
        description = item.get("description")
        confidence = item.get("confidence")
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError) as exc:
                raise LLMExtractorError(
                    f"Invalid confidence at index {index}"
                ) from exc

        description_str = (
            str(description) if description is not None else None
        )
        transactions.append(
            Transaction(
                account_id=str(account_id)
                if account_id is not None
                else None,
                currency=str(currency).upper()
                if currency is not None
                else None,
                amount=amount,
                booking_date=_safe_date(item.get("booking_date")),
                value_date=_safe_date(item.get("booking_date")),
                description=description_str,
                normalized_description=normalize_description(
                    description_str
                ),
                reference=(
                    str(item.get("reference"))
                    if item.get("reference") is not None
                    else None
                ),
                source="llm",
                source_index=index,
                source_method="llm",
                confidence=confidence,
                raw_source_text=_slice_source_context(
                    description_str, source_text
                ),
            )
        )

    return LLMExtractionResult(
        account_id=str(account_id) if account_id is not None else None,
        currency=str(currency).upper() if currency is not None else None,
        opening_balance=opening,
        closing_balance=closing,
        transactions=transactions,
        raw_response=raw,
    )


def _safe_date(value: Any) -> Any:
    """Pass dates straight through; Transaction handles parsing."""
    from datetime import date, datetime

    if value in (None, ""):
        return None
    if isinstance(value, (date, datetime)):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise LLMExtractorError(
            f"Invalid booking_date from LLM: {value!r}"
        ) from exc
