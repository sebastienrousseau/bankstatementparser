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

"""Direct Ollama completion bridge that bypasses LiteLLM.

LiteLLM's Ollama adapter has a reproducible bug where vision calls
with long structured-JSON system prompts hang at the 600 s timeout.
The same prompt sent directly to Ollama's ``/api/chat`` endpoint
completes in ~18 s on Apple Silicon Metal — verified during the
v0.0.5 smoke test.

This module exposes :func:`ollama_direct_completion`, a drop-in
replacement for ``litellm.completion`` that targets Ollama
directly. It accepts the same OpenAI-style ``messages`` shape that
:class:`~.llm_extractor.LLMExtractor` and
:class:`~.vision.VisionExtractor` already build, and it returns a
response object that the existing JSON-parsing helpers can consume
without modification.

Auto-selection: when a vision/text extractor is constructed with
``model.startswith("ollama/")`` and no explicit ``completion_fn``,
the extractor uses this helper automatically. Users do not need to
opt in.

Why this is in the library and not just a documentation snippet:
the workaround is small, well-bounded, and adds no new optional
dependencies (``httpx`` is already a transitive dep of LiteLLM in
the ``[hybrid]`` extra). Shipping it as a built-in turns the only
remaining ⚠️ in the cross-platform matrix into a ✅ for every
local-Ollama user.
"""

from __future__ import annotations

import base64
import os
import re
from typing import Any

DEFAULT_API_BASE = "http://localhost:11434"
ENV_API_BASE = "BSP_HYBRID_API_BASE"

# Strip the LiteLLM provider prefix so the Ollama API receives a
# bare model name. Matches "ollama/", "ollama_chat/", or any other
# slash-prefixed router LiteLLM might use for the same backend.
_PROVIDER_PREFIX_RE = re.compile(r"^ollama(?:_chat)?/", re.IGNORECASE)


class OllamaDirectError(RuntimeError):
    """Raised when the direct Ollama call fails or returns garbage."""


def ollama_direct_completion(**kwargs: Any) -> dict[str, Any]:
    """Translate a LiteLLM-style call into a direct Ollama ``/api/chat`` call.

    Accepted keyword arguments (the same shape ``litellm.completion``
    consumes):

    Args:
        model: ``ollama/<name>`` or just ``<name>``. The provider
            prefix is stripped automatically.
        messages: OpenAI-style messages list. May contain
            multimodal content blocks (``{"type": "image_url",
            "image_url": {"url": "data:image/png;base64,..."}}``).
        temperature: Sampling temperature, defaults to ``0.0``.
        api_base: Override for ``http://localhost:11434``. Reads
            ``BSP_HYBRID_API_BASE`` if not provided.
        timeout: HTTP timeout in seconds, defaults to ``300``.

    Returns:
        An OpenAI-style response dict with a single
        ``choices[0].message.content`` entry that the existing
        JSON-parsing helpers can consume.

    Raises:
        OllamaDirectError: When httpx is missing, the request
            fails, or the response shape is unexpected.
    """
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - optional dep
        raise OllamaDirectError(
            "httpx is required for the direct Ollama bridge. "
            "Install with: pip install bankstatementparser[hybrid]"
        ) from exc

    model = kwargs.get("model", "")
    if not model:
        raise OllamaDirectError("model is required")
    bare_model = _PROVIDER_PREFIX_RE.sub("", model)

    raw_messages = kwargs.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise OllamaDirectError("messages must be a non-empty list")
    ollama_messages = [
        _convert_message(msg) for msg in raw_messages
    ]

    api_base = (
        kwargs.get("api_base")
        or os.environ.get(ENV_API_BASE)
        or DEFAULT_API_BASE
    )
    timeout = float(kwargs.get("timeout", 300.0))
    temperature = float(kwargs.get("temperature", 0.0))

    payload: dict[str, Any] = {
        "model": bare_model,
        "messages": ollama_messages,
        "stream": False,
        "options": {"temperature": temperature},
    }

    try:
        response = httpx.post(
            f"{api_base.rstrip('/')}/api/chat",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        raise OllamaDirectError(
            f"Direct Ollama call failed: {exc}"
        ) from exc

    content = data.get("message", {}).get("content")
    if not isinstance(content, str):
        raise OllamaDirectError(
            f"Unexpected Ollama response shape: {data!r}"
        )

    # Wrap in an OpenAI-style envelope so _extract_message_content
    # in llm_extractor.py works without modification.
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}}
        ]
    }


def _convert_message(message: dict[str, Any]) -> dict[str, Any]:
    """Translate one OpenAI-style message into Ollama's format.

    Ollama's ``/api/chat`` accepts a flat ``content`` string per
    message and a separate ``images`` array of base64 strings.
    OpenAI uses a structured ``content`` list with ``text`` and
    ``image_url`` blocks. This function unpacks the latter into
    Ollama's flat shape.
    """
    role = message.get("role", "user")
    content = message.get("content")

    if isinstance(content, str):
        return {"role": role, "content": content}

    if not isinstance(content, list):
        raise OllamaDirectError(
            f"Unsupported message content type: {type(content).__name__}"
        )

    text_parts: list[str] = []
    images: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(str(block.get("text", "")))
        elif block_type == "image_url":
            url = block.get("image_url", {}).get("url", "")
            images.append(_strip_data_url(url))

    out: dict[str, Any] = {
        "role": role,
        "content": "\n".join(text_parts),
    }
    if images:
        out["images"] = images
    return out


def _strip_data_url(url: str) -> str:
    """Return only the base64 payload from a ``data:image/...;base64,`` URL."""
    if "," in url:
        return url.split(",", 1)[1]
    # Assume it's already raw base64. Validate by attempting decode
    # so corrupt input fails loudly instead of being sent to Ollama.
    try:
        base64.b64decode(url, validate=True)
    except Exception as exc:
        raise OllamaDirectError(
            f"Invalid image_url payload: {exc}"
        ) from exc
    return url


def is_ollama_model(model: str | None) -> bool:
    """Return True when ``model`` should use the direct bridge.

    Used by :class:`~.vision.VisionExtractor` and
    :class:`~.llm_extractor.LLMExtractor` to auto-select the
    bypass when no explicit ``completion_fn`` was provided.
    """
    if not model:
        return False
    return bool(_PROVIDER_PREFIX_RE.match(model))
