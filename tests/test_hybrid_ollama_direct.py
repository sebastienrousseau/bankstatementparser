# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the direct Ollama bridge that bypasses LiteLLM."""

from __future__ import annotations

import base64
import sys
import types
from typing import Any

import pytest

from bankstatementparser.hybrid import ollama_direct as od
from bankstatementparser.hybrid.ollama_direct import (
    OllamaDirectError,
    is_ollama_model,
    ollama_direct_completion,
)

# ---------------------------------------------------------------------------
# Fake httpx so the tests don't need a running Ollama instance
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        status_code: int = 200,
    ) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


def _install_fake_httpx(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response_payload: dict[str, Any] | None = None,
    raise_on_post: Exception | None = None,
    capture: dict[str, Any] | None = None,
) -> None:
    fake = types.ModuleType("httpx")

    def fake_post(url: str, json: dict[str, Any], timeout: float):
        if capture is not None:
            capture["url"] = url
            capture["json"] = json
            capture["timeout"] = timeout
        if raise_on_post is not None:
            raise raise_on_post
        return _FakeResponse(
            response_payload
            or {
                "message": {
                    "role": "assistant",
                    "content": '{"transactions": []}',
                }
            }
        )

    fake.post = fake_post  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake)


# ---------------------------------------------------------------------------
# is_ollama_model
# ---------------------------------------------------------------------------


def test_is_ollama_model_true_for_ollama_prefix() -> None:
    assert is_ollama_model("ollama/llama3") is True
    assert is_ollama_model("ollama/llava") is True
    assert is_ollama_model("ollama_chat/llama3") is True
    assert is_ollama_model("OLLAMA/llava") is True


def test_is_ollama_model_false_otherwise() -> None:
    assert is_ollama_model(None) is False
    assert is_ollama_model("") is False
    assert is_ollama_model("gpt-4o") is False
    assert is_ollama_model("anthropic/claude-3-haiku") is False
    assert is_ollama_model("llama3") is False  # no provider prefix


# ---------------------------------------------------------------------------
# ollama_direct_completion — happy paths
# ---------------------------------------------------------------------------


def test_strips_provider_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, capture=captured)

    ollama_direct_completion(
        model="ollama/llava",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert captured["json"]["model"] == "llava"


def test_strips_ollama_chat_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, capture=captured)

    ollama_direct_completion(
        model="ollama_chat/llama3",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert captured["json"]["model"] == "llama3"


def test_passes_temperature_and_streaming_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, capture=captured)

    ollama_direct_completion(
        model="ollama/llava",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.0,
    )

    assert captured["json"]["stream"] is False
    assert captured["json"]["options"]["temperature"] == 0.0


def test_default_api_base_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BSP_HYBRID_API_BASE", raising=False)
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, capture=captured)

    ollama_direct_completion(
        model="ollama/llava",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert captured["url"] == "http://localhost:11434/api/chat"


def test_explicit_api_base_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BSP_HYBRID_API_BASE", "http://wrong:1234")
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, capture=captured)

    ollama_direct_completion(
        model="ollama/llava",
        messages=[{"role": "user", "content": "hi"}],
        api_base="http://right:11434",
    )

    assert captured["url"] == "http://right:11434/api/chat"


def test_env_api_base_used_when_no_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "BSP_HYBRID_API_BASE", "http://host.docker.internal:11434"
    )
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, capture=captured)

    ollama_direct_completion(
        model="ollama/llava",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert captured["url"].startswith("http://host.docker.internal")


def test_returns_openai_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(
        monkeypatch,
        response_payload={
            "message": {
                "role": "assistant",
                "content": '{"transactions": [{"x": 1}]}',
            }
        },
    )

    result = ollama_direct_completion(
        model="ollama/llava",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert "choices" in result
    assert (
        result["choices"][0]["message"]["content"]
        == '{"transactions": [{"x": 1}]}'
    )


# ---------------------------------------------------------------------------
# Multimodal message conversion
# ---------------------------------------------------------------------------


def test_unpacks_multimodal_content_into_ollama_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, capture=captured)

    img_b64 = base64.b64encode(b"PNG_BYTES").decode("ascii")
    ollama_direct_completion(
        model="ollama/llava",
        messages=[
            {"role": "system", "content": "You are a parser."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract this:"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}",
                        },
                    },
                ],
            },
        ],
    )

    sent_messages = captured["json"]["messages"]
    assert sent_messages[0] == {
        "role": "system",
        "content": "You are a parser.",
    }
    user = sent_messages[1]
    assert user["role"] == "user"
    assert user["content"] == "Extract this:"
    assert user["images"] == [img_b64]


def test_accepts_raw_base64_images_without_data_url_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, capture=captured)

    img_b64 = base64.b64encode(b"PNG_BYTES").decode("ascii")
    ollama_direct_completion(
        model="ollama/llava",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "x"},
                    {
                        "type": "image_url",
                        "image_url": {"url": img_b64},
                    },
                ],
            }
        ],
    )

    assert captured["json"]["messages"][0]["images"] == [img_b64]


def test_skips_unknown_content_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, capture=captured)

    ollama_direct_completion(
        model="ollama/llava",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "alpha"},
                    {"type": "video_url", "video_url": {"url": "x"}},
                    "not a dict",
                    {"type": "text", "text": "beta"},
                ],
            }
        ],
    )

    assert captured["json"]["messages"][0]["content"] == "alpha\nbeta"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_raises_when_model_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch)
    with pytest.raises(OllamaDirectError, match="model is required"):
        ollama_direct_completion(messages=[{"role": "user", "content": "hi"}])


def test_raises_when_messages_missing_or_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch)
    with pytest.raises(
        OllamaDirectError, match="messages must be a non-empty list"
    ):
        ollama_direct_completion(model="ollama/llava")
    with pytest.raises(
        OllamaDirectError, match="messages must be a non-empty list"
    ):
        ollama_direct_completion(model="ollama/llava", messages=[])


def test_raises_on_unsupported_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch)
    with pytest.raises(
        OllamaDirectError, match="Unsupported message content type"
    ):
        ollama_direct_completion(
            model="ollama/llava",
            messages=[{"role": "user", "content": 42}],
        )


def test_raises_on_invalid_raw_base64_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(monkeypatch)
    with pytest.raises(
        OllamaDirectError, match="Invalid image_url payload"
    ):
        ollama_direct_completion(
            model="ollama/llava",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "!!!not-base64!!!"},
                        }
                    ],
                }
            ],
        )


def test_wraps_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(
        monkeypatch, raise_on_post=ConnectionError("refused")
    )
    with pytest.raises(
        OllamaDirectError, match="Direct Ollama call failed"
    ):
        ollama_direct_completion(
            model="ollama/llava",
            messages=[{"role": "user", "content": "hi"}],
        )


def test_wraps_unexpected_response_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_httpx(
        monkeypatch, response_payload={"unexpected": "shape"}
    )
    with pytest.raises(
        OllamaDirectError, match="Unexpected Ollama response shape"
    ):
        ollama_direct_completion(
            model="ollama/llava",
            messages=[{"role": "user", "content": "hi"}],
        )


# ---------------------------------------------------------------------------
# Auto-selection in extractors
# ---------------------------------------------------------------------------


def test_vision_extractor_auto_selects_direct_bridge_for_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bankstatementparser.hybrid.vision import VisionExtractor

    _install_fake_httpx(monkeypatch)
    ext = VisionExtractor(model="ollama/llava")
    fn = ext._resolve_completion()
    assert fn is od.ollama_direct_completion


def test_llm_extractor_auto_selects_direct_bridge_for_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bankstatementparser.hybrid.llm_extractor import LLMExtractor

    _install_fake_httpx(monkeypatch)
    ext = LLMExtractor(model="ollama/llama3")
    fn = ext._resolve_completion()
    assert fn is od.ollama_direct_completion


def test_extractors_skip_direct_bridge_for_non_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bankstatementparser.hybrid.llm_extractor import LLMExtractor

    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = lambda **_: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    ext = LLMExtractor(model="anthropic/claude-3-haiku")
    fn = ext._resolve_completion()
    assert fn is fake_litellm.completion
