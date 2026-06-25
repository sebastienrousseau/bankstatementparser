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

"""LiteLLM-backed transaction categorizer.

This module is the only piece of :mod:`bankstatementparser` that
returns *opinions* (a category label, an is-business-expense
boolean) rather than *facts* extracted from the source statement.
It lives behind the ``[enrichment]`` install extra so the
deterministic core stays opinion-free.

Wrapper rather than mutator
---------------------------

The categorizer returns :class:`EnrichedTransaction` instances that
hold the original :class:`Transaction` plus the inferred fields.
The original ``Transaction`` is **never mutated** — it is the only
field on ``EnrichedTransaction``, accessible as ``et.transaction``.
This guarantees that:

* The deterministic ``Transaction.transaction_hash`` stays stable
  even after enrichment, so downstream dedup and idempotent
  ingestion still work.
* Auditors can always recover the original "facts from source" by
  ignoring the wrapper fields.
* Removing categorization from the pipeline never loses data.

Pluggable schema
----------------

:data:`DEFAULT_CATEGORY_SCHEMA` is the Plaid 13-category taxonomy,
which is well-known and broadly applicable for personal-finance
use cases. Users with their own taxonomy (Xero, IRS Schedule C, a
custom internal one) pass their own list of category strings to
:class:`Categorizer`. The categorizer treats the schema as opaque
and just instructs the LLM to pick from the provided list.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from .._llm_common import (
    DEFAULT_MODEL as DEFAULT_ENRICHMENT_MODEL,
)
from .._llm_common import (
    ENV_ENRICHMENT_MODEL,
    extract_message_content,
    parse_confidence,
    parse_json_payload,
    warn_if_data_leaves_machine,
)
from .._llm_common import (
    ENV_MODEL as ENV_FALLBACK_MODEL,
)
from ..transaction_models import Transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default category schema
# ---------------------------------------------------------------------------

# Plaid's 13-category taxonomy. Broadly applicable for personal
# finance and small-business use cases. Users with a different
# taxonomy (Xero, IRS Schedule C, etc.) pass their own list to
# :class:`Categorizer`.
DEFAULT_CATEGORY_SCHEMA: tuple[str, ...] = (
    "Bank Fees",
    "Cash Advance",
    "Community",
    "Food and Drink",
    "Healthcare",
    "Interest",
    "Payment",
    "Recreation",
    "Service",
    "Shops",
    "Tax",
    "Transfer",
    "Travel",
)

CompletionFn = Callable[..., Any]


class CategorizerError(RuntimeError):
    """Raised when the enrichment LLM call or its parsing fails."""


class EnrichedTransaction(BaseModel):
    """A :class:`Transaction` plus inferred enrichment fields.

    The wrapper composition (rather than inheritance) is deliberate:
    the original ``Transaction`` stays unchanged, so dedup keys,
    audit trails, and serialization that doesn't know about
    enrichment all keep working.
    """

    model_config = ConfigDict(frozen=True)

    transaction: Transaction
    category: Optional[str] = None
    is_business_expense: Optional[bool] = None
    enrichment_confidence: Optional[float] = None
    rationale: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


SYSTEM_PROMPT_TEMPLATE = """You are a meticulous Personal Finance
Categorizer. You receive a list of bank-statement transactions and
return a category label for each one, drawn ONLY from this fixed
schema:

{schema_block}

For every transaction you also return:
  * is_business_expense — true if the row is plausibly a business
    expense (B2B vendor, software subscription, professional
    service); false for personal spending; null if you genuinely
    cannot tell. THIS IS A LABEL, NOT TAX ADVICE.
  * confidence — 0.0 to 1.0
  * rationale — a single short sentence explaining the choice

Output ONLY a single JSON object with this shape — no prose, no
markdown:

{{
  "results": [
    {{
      "index": 0,
      "category": "Food and Drink",
      "is_business_expense": false,
      "confidence": 0.92,
      "rationale": "Coffee shop transaction"
    }},
    ...
  ]
}}

Return exactly one result per input transaction, in the same order
the inputs were given. The "index" field MUST match the input
position. If you genuinely cannot categorize a row, return
"category": null and explain why in the rationale.
"""

USER_PROMPT_TEMPLATE = """Categorize the following {count} transactions.
Return the JSON array described in the system prompt.

{rows}
"""


def _build_messages(
    transactions: list[Transaction],
    schema: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Build the system/user message pair for a categorization call."""
    schema_block = "\n".join(f"  - {c}" for c in schema)
    rows = "\n".join(
        _format_row(idx, tx) for idx, tx in enumerate(transactions)
    )
    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT_TEMPLATE.format(
                schema_block=schema_block,
            ),
        },
        {
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                count=len(transactions),
                rows=rows,
            ),
        },
    ]


def _sanitize_for_prompt(value: str) -> str:
    """Strip control characters and common injection markers.

    Bank statement descriptions are untrusted text interpolated into
    an LLM prompt. No sanitizer is perfect against prompt injection,
    but stripping control characters and known markers like
    ``[SYSTEM``, ``[INST`` makes casual injection substantially
    harder and prevents the most common attack patterns.
    """
    # 1. Strip ASCII control characters (0x00-0x1F except newline)
    cleaned = re.sub(r"[\x00-\x09\x0b-\x1f]", "", value)
    # 2. Collapse markdown/instruction markers
    cleaned = cleaned.replace("[SYSTEM", "[SYS_").replace("[INST", "[INS_")
    # 3. Strip backtick fences that could close a code block
    cleaned = cleaned.replace("```", "")
    return cleaned


def _format_row(index: int, tx: Transaction) -> str:
    """Render one transaction as a single prompt line."""
    date = tx.booking_date.isoformat() if tx.booking_date else "????-??-??"
    desc = _sanitize_for_prompt(tx.description or "(no description)")
    return f"  [{index}] {date}  {tx.amount:>10}  {desc[:80]}"


# ---------------------------------------------------------------------------
# Categorizer
# ---------------------------------------------------------------------------


@dataclass
class Categorizer:
    """LiteLLM-backed transaction categorizer.

    .. warning::

        **Not thread-safe.** Instantiate one ``Categorizer`` per
        thread if you need concurrent categorization. The
        ``completion_fn`` callback is shared mutable state; calling
        ``categorize_batch()`` from multiple threads on the same
        instance may produce race conditions in the LLM client.

    Args:
        schema: Tuple of category strings the LLM is allowed to
            pick from. Defaults to :data:`DEFAULT_CATEGORY_SCHEMA`.
        model: LiteLLM model id. Defaults to
            ``BSP_HYBRID_ENRICHMENT_MODEL``, then
            ``BSP_HYBRID_MODEL``, then
            :data:`DEFAULT_ENRICHMENT_MODEL`.
        api_base: Optional API base override.
        completion_fn: Injectable completion callable for testing.
        batch_size: Number of transactions to send to the LLM in a
            single call. Defaults to 25 to keep prompts under most
            providers' practical context limits.
    """

    schema: tuple[str, ...] = DEFAULT_CATEGORY_SCHEMA
    model: Optional[str] = None
    api_base: Optional[str] = None
    completion_fn: Optional[CompletionFn] = None
    batch_size: int = 25
    _resolved_model: str = field(init=False, default="")

    _schema_lookup: dict[str, str] = field(
        init=False, default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        """Validate configuration and resolve the model id.

        Raises:
            ValueError: If ``schema`` is empty or ``batch_size`` is
                less than 1.
        """
        if not self.schema:
            raise ValueError("schema must be a non-empty tuple")
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._resolved_model = (
            self.model
            or os.environ.get(ENV_ENRICHMENT_MODEL)
            or os.environ.get(ENV_FALLBACK_MODEL)
            or DEFAULT_ENRICHMENT_MODEL
        )
        warn_if_data_leaves_machine(self._resolved_model, self.api_base)
        # Cache once instead of rebuilding per chunk
        self._schema_lookup = {c.lower(): c for c in self.schema}

    def categorize(self, transaction: Transaction) -> EnrichedTransaction:
        """Convenience wrapper for single-row categorization."""
        results = self.categorize_batch([transaction])
        return results[0]

    def categorize_batch(
        self,
        transactions: Iterable[Transaction],
    ) -> list[EnrichedTransaction]:
        """Categorize a list of transactions in batches.

        Splits the input into chunks of :attr:`batch_size`, calls
        the LLM for each chunk, and returns one
        :class:`EnrichedTransaction` per input row in the same
        order. If a chunk fails, the rows in that chunk are still
        returned but with ``category=None`` and the failure
        reported in ``rationale``.
        """
        items = list(transactions)
        if not items:
            return []

        out: list[EnrichedTransaction] = []
        for chunk_start in range(0, len(items), self.batch_size):
            chunk = items[chunk_start : chunk_start + self.batch_size]
            try:
                out.extend(self._categorize_chunk(chunk))
            except CategorizerError as exc:
                # Surface the failure as None-categories for the
                # whole chunk so callers can still see every input
                # row in the output. The audit trail makes the
                # failure visible without losing data.
                out.extend(
                    EnrichedTransaction(
                        transaction=tx,
                        rationale=f"categorization failed: {exc}",
                    )
                    for tx in chunk
                )
        return out

    def _categorize_chunk(
        self,
        chunk: list[Transaction],
    ) -> list[EnrichedTransaction]:
        """Categorize a single chunk of transactions via one LLM call."""
        completion = self._resolve_completion()
        messages = _build_messages(chunk, self.schema)

        kwargs: dict[str, Any] = {
            "model": self._resolved_model,
            "messages": messages,
            "temperature": 0.0,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base

        try:
            response = completion(**kwargs)
        except Exception as exc:
            raise CategorizerError(
                f"Enrichment completion failed: {exc}"
            ) from exc

        raw = _extract_message_content(response)
        payload = _parse_json_payload(raw)
        return _build_enriched(chunk, payload, self._schema_lookup)

    def _resolve_completion(self) -> CompletionFn:
        """Return the injected completion callable or import LiteLLM's."""
        if self.completion_fn is not None:
            return self.completion_fn
        try:
            from litellm import completion
        except ImportError as exc:
            raise CategorizerError(
                "litellm is required for the enrichment module. "
                "Install with: pip install bankstatementparser[enrichment]"
            ) from exc
        return completion  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _extract_message_content(response: Any) -> str:
    """Pull the assistant message content out of an OpenAI-style response."""
    return extract_message_content(response, error_cls=CategorizerError)


def _parse_json_payload(raw: str) -> dict[str, Any]:
    """Tolerantly parse a JSON object from a model response."""
    return parse_json_payload(raw, error_cls=CategorizerError)


def _build_enriched(
    chunk: list[Transaction],
    payload: dict[str, Any],
    schema_lookup: dict[str, str],
) -> list[EnrichedTransaction]:
    """Map an LLM results payload back onto the input chunk by index."""
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise CategorizerError("Enrichment payload missing 'results' list")

    by_index: dict[int, dict[str, Any]] = {}
    for entry in raw_results:
        if not isinstance(entry, dict):
            raise CategorizerError(
                "Enrichment 'results' entries must be objects"
            )
        idx = entry.get("index")
        if not isinstance(idx, int):
            raise CategorizerError(
                "Enrichment 'results' entry missing integer 'index'"
            )
        if idx in by_index:
            logger.warning(
                "LLM returned duplicate index %d; last entry wins",
                idx,
            )
        by_index[idx] = entry
    out: list[EnrichedTransaction] = []
    for index, tx in enumerate(chunk):
        entry = by_index.get(index)
        if entry is None:
            out.append(
                EnrichedTransaction(
                    transaction=tx,
                    rationale="LLM did not return a result for this row",
                )
            )
            continue

        category = entry.get("category")
        if isinstance(category, str):
            normalized = schema_lookup.get(category.strip().lower())
            category = normalized  # may be None if not in schema
        else:
            category = None

        is_business = entry.get("is_business_expense")
        if not isinstance(is_business, bool):
            is_business = None

        # Best-effort: enrichment is advisory, so a hallucinated or
        # out-of-range confidence degrades to None instead of
        # failing the whole chunk.
        try:
            confidence = parse_confidence(
                entry.get("confidence"),
                error_cls=CategorizerError,
            )
        except CategorizerError:
            confidence = None

        rationale_raw = entry.get("rationale")
        rationale = str(rationale_raw) if rationale_raw is not None else None

        out.append(
            EnrichedTransaction(
                transaction=tx,
                category=category,
                is_business_expense=is_business,
                enrichment_confidence=confidence,
                rationale=rationale,
            )
        )
    return out
