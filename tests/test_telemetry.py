# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for structured telemetry and OpenTelemetry integration."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from bankstatementparser.telemetry import (
    NullSpan,
    is_telemetry_available,
    trace_async_stream,
    trace_span,
    trace_stream,
    traced,
)


def test_null_span_attributes_and_status() -> None:
    """NullSpan records attributes, statuses, and exceptions."""
    span = NullSpan("test_span", {"initial": 1})
    assert span.name == "test_span"
    assert span.attributes == {"initial": 1}

    span.set_attribute("extra", "value")
    assert span.attributes["extra"] == "value"

    span.set_status("ERROR", "Something broke")
    assert span.status == ("ERROR", "Something broke")

    exc = ValueError("boom")
    span.record_exception(exc)
    assert span.exceptions == [exc]


def test_null_span_context_manager() -> None:
    """NullSpan captures exceptions occurring inside its context."""
    with NullSpan("span") as span:
        span.set_attribute("k", "v")
    assert span.attributes == {"k": "v"}
    assert len(span.exceptions) == 0

    span_with_exc = NullSpan("span_err")
    with pytest.raises(RuntimeError, match="test error"):
        with span_with_exc:
            raise RuntimeError("test error")
    assert len(span_with_exc.exceptions) == 1
    assert isinstance(span_with_exc.exceptions[0], RuntimeError)


def test_is_telemetry_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Check detection of OpenTelemetry availability."""
    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", None)
    assert not is_telemetry_available()

    fake_otel = types.ModuleType("opentelemetry")
    fake_trace = types.ModuleType("opentelemetry.trace")
    fake_otel.trace = fake_trace  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_otel)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", fake_trace)
    assert is_telemetry_available()


def test_trace_span_with_opentelemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """trace_span delegates to OpenTelemetry when available."""
    mock_tracer = MagicMock()
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = (
        mock_span
    )

    fake_trace = types.ModuleType("opentelemetry.trace")
    fake_trace.get_tracer = MagicMock(return_value=mock_tracer)  # type: ignore[attr-defined]

    fake_otel = types.ModuleType("opentelemetry")
    fake_otel.trace = fake_trace  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "opentelemetry", fake_otel)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", fake_trace)

    with trace_span("operation", attributes={"tag": "demo"}) as span:
        assert span is mock_span

    fake_trace.get_tracer.assert_called_once_with("bankstatementparser")
    mock_tracer.start_as_current_span.assert_called_once_with(
        "operation", attributes={"tag": "demo"}
    )


def test_traced_decorator_sync() -> None:
    """traced wraps sync callables in spans."""

    @traced("my_sync_op", {"scope": "test"})
    def compute(x: int) -> int:
        return x * 2

    assert compute(5) == 10

    @traced()
    def default_named() -> str:
        return "ok"

    assert default_named() == "ok"


def test_traced_decorator_async() -> None:
    """traced wraps async coroutines in spans."""

    @traced("my_async_op")
    async def fetch_data() -> str:
        return "async_result"

    res = asyncio.run(fetch_data())
    assert res == "async_result"


def test_trace_stream() -> None:
    """trace_stream yields all items and records the total item count."""
    items = [1, 2, 3, 4]
    consumed = list(trace_stream("stream_test", iter(items), {"type": "test"}))
    assert consumed == items


def test_trace_async_stream() -> None:
    """trace_async_stream yields all items asynchronously."""

    async def gen() -> Any:
        for i in range(3):
            yield i

    async def consume() -> list[int]:
        result = []
        async for x in trace_async_stream("async_stream", gen()):
            result.append(x)
        return result

    assert asyncio.run(consume()) == [0, 1, 2]
