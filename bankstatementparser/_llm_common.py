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

"""Shared LLM plumbing for the hybrid and enrichment extras.

Single home for the environment-variable names, the OpenAI-style
response unwrapping, and the tolerant-but-strict JSON payload
parsing that both :mod:`bankstatementparser.hybrid` and
:mod:`bankstatementparser.enrichment` need. Previously these were
copy-pasted between ``hybrid/llm_extractor.py`` and
``enrichment/categorizer.py`` and had started to drift.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Environment variables shared across the LLM-backed extras.
ENV_MODEL = "BSP_HYBRID_MODEL"
ENV_VISION_MODEL = "BSP_HYBRID_VISION_MODEL"
ENV_ENRICHMENT_MODEL = "BSP_HYBRID_ENRICHMENT_MODEL"
ENV_API_BASE = "BSP_HYBRID_API_BASE"

DEFAULT_MODEL = "ollama/llama3"
DEFAULT_API_BASE = "http://localhost:11434"

# LiteLLM provider prefixes that route to a local Ollama daemon.
OLLAMA_PREFIX_RE = re.compile(r"^ollama(?:_chat)?/", re.IGNORECASE)

_LOCAL_HOSTNAMES = frozenset(
    # Matched against, never bound to — this is an allowlist of local hosts
    {"localhost", "127.0.0.1", "::1", "0.0.0.0"}  # noqa: S104  # nosec B104
)

# (model, api_base) pairs already warned about, so a batch run
# doesn't repeat the privacy warning once per file.
_warned_destinations: set[tuple[str, str]] = set()


def _is_local_api_base(api_base: Optional[str]) -> bool:
    """Return whether an API base URL points at the local machine."""
    if not api_base:
        return True
    host = urlparse(api_base).hostname or ""
    return host.lower() in _LOCAL_HOSTNAMES


def warn_if_data_leaves_machine(
    model: Optional[str], api_base: Optional[str] = None
) -> None:
    """Warn (once per destination) when statement data goes off-box.

    Statement text and page images contain account numbers, names,
    and addresses. The default ``ollama/*`` + localhost setup keeps
    everything on the local machine; any other provider or a
    non-local ``api_base`` transmits that data to a third party.
    This is a deliberate, supported configuration — but it must
    never happen silently.
    """
    if not model:
        return
    if OLLAMA_PREFIX_RE.match(model) and _is_local_api_base(api_base):
        return
    key = (model, api_base or "")
    if key in _warned_destinations:
        return
    _warned_destinations.add(key)
    destination = api_base or f"the provider behind '{model}'"
    logger.warning(
        "Statement content (which can include account numbers, "
        "names, and addresses) will be sent to a remote LLM "
        "endpoint: %s. Use a local ollama/* model with a localhost "
        "api_base to keep data on this machine.",
        destination,
    )


def extract_message_content(
    response: Any, *, error_cls: type[Exception] = RuntimeError
) -> str:
    """Pull the assistant message text from an OpenAI-style response."""
    try:
        if isinstance(response, dict):
            content = response["choices"][0]["message"]["content"]
        else:
            content = response.choices[0].message.content
    except (AttributeError, KeyError, IndexError, TypeError) as exc:
        raise error_cls(f"Unexpected LLM response shape: {exc}") from exc
    if not isinstance(content, str) or not content.strip():
        raise error_cls("LLM returned empty content")
    return content


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_json_payload(
    raw: str, *, error_cls: type[Exception] = RuntimeError
) -> dict[str, Any]:
    """Parse a single JSON object out of a model response.

    Accepts a fenced ```json block or a bare object embedded in
    prose. Uses ``JSONDecoder.raw_decode`` from the first ``{`` so
    trailing prose or a second JSON object after the payload cannot
    corrupt the parse (the old ``find("{")``/``rfind("}")`` slice
    produced invalid JSON whenever the model emitted two objects).
    """
    text = raw.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise error_cls(f"LLM did not return valid JSON: {exc}") from exc
    else:
        start = text.find("{")
        if start == -1:
            raise error_cls("LLM did not return valid JSON: no object found")
        try:
            payload, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            raise error_cls(f"LLM did not return valid JSON: {exc}") from exc
    if not isinstance(payload, dict):  # pragma: no cover
        # Unreachable today: both branches above decode starting at a
        # "{", which can only yield a dict or raise. Kept as a guard
        # in case the fence regex is ever widened to arrays.
        raise error_cls("LLM JSON payload must be an object")
    return payload


def parse_confidence(
    value: Any,
    *,
    context: str = "",
    error_cls: type[Exception] = RuntimeError,
) -> Optional[float]:
    """Validate an LLM-supplied confidence into the 0.0-1.0 range.

    LLM output is untrusted: a hallucinated ``1e308`` or ``-3``
    must not flow into downstream review logic as a plausible
    score.
    """
    if value is None:
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise error_cls(f"Invalid confidence{context}: {value!r}") from exc
    if not 0.0 <= confidence <= 1.0:
        raise error_cls(f"Confidence{context} out of range [0, 1]: {value!r}")
    return confidence
