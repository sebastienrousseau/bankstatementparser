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

"""Structured telemetry and OpenTelemetry tracing hooks.

Provides lightweight zero-dependency tracing hooks with automatic
OpenTelemetry delegation when ``opentelemetry`` is installed.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal, TypeVar, cast

logger = logging.getLogger(__name__)

T = TypeVar("T")

__all__ = [
    "NullSpan",
    "is_telemetry_available",
    "trace_async_stream",
    "trace_span",
    "trace_stream",
    "traced",
]


def is_telemetry_available() -> bool:
    """Return whether OpenTelemetry is installed and available."""
    try:
        import opentelemetry.trace  # noqa: F401

        return True
    except ImportError:
        return False


class NullSpan:
    """Fallback in-memory span used when OpenTelemetry is unavailable."""

    def __init__(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the fallback span with a name and optional attributes."""
        self.name = name
        self.attributes: dict[str, Any] = dict(attributes or {})
        self.status: tuple[str, str | None] = ("OK", None)
        self.exceptions: list[BaseException] = []

    def set_attribute(self, key: str, value: Any) -> None:
        """Record an attribute on the span."""
        self.attributes[key] = value

    def set_status(self, status: Any, description: str | None = None) -> None:
        """Record status on the span."""
        self.status = (str(status), description)

    def record_exception(self, exception: BaseException) -> None:
        """Record an exception that occurred in the span."""
        self.exceptions.append(exception)

    def __enter__(self) -> NullSpan:
        """Enter span context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> Literal[False]:
        """Exit span context, capturing exceptions if present."""
        if exc_val is not None:
            self.record_exception(exc_val)
        return False


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Execute a block within an active tracing span.

    Uses OpenTelemetry if available; otherwise uses :class:`NullSpan`.
    """
    if is_telemetry_available():
        from opentelemetry import trace

        tracer = trace.get_tracer("bankstatementparser")
        with tracer.start_as_current_span(name, attributes=attributes) as span:
            yield span
    else:
        with NullSpan(name, attributes=attributes) as span:
            yield span


def traced(
    name: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorate a sync or async callable to execute inside a tracing span."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        """Wrap callable with span execution."""
        span_name = name or fn.__qualname__

        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                """Execute coroutine inside trace_span."""
                with trace_span(span_name, attributes):
                    return await fn(*args, **kwargs)

            return cast(Callable[..., T], async_wrapper)

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            """Execute sync function inside trace_span."""
            with trace_span(span_name, attributes):
                return fn(*args, **kwargs)

        return sync_wrapper

    return decorator


def trace_stream(
    name: str,
    iterable: Iterator[T],
    attributes: dict[str, Any] | None = None,
) -> Iterator[T]:
    """Wrap an iterator in a tracing span, recording the yield count."""
    with trace_span(name, attributes) as span:
        count = 0
        try:
            for item in iterable:
                count += 1
                yield item
        finally:
            span.set_attribute("item_count", count)


async def trace_async_stream(
    name: str,
    iterable: AsyncIterator[T],
    attributes: dict[str, Any] | None = None,
) -> AsyncIterator[T]:
    """Wrap an async iterator in a tracing span, recording the yield count."""
    with trace_span(name, attributes) as span:
        count = 0
        try:
            async for item in iterable:
                count += 1
                yield item
        finally:
            span.set_attribute("item_count", count)
