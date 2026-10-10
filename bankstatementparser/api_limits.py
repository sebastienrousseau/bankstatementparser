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

"""Upload bounds and admission limits for the REST API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from .input_validator import InputValidator

logger = logging.getLogger(__name__)

# Maximum upload size in bytes. Real bank statements are well under
# a megabyte; 25 MB is generous and bounds the worst-case memory
# spike per request. Override via ``BSP_API_MAX_UPLOAD_BYTES``.
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ENV_MAX_UPLOAD_BYTES = "BSP_API_MAX_UPLOAD_BYTES"

# Streaming chunk size for upload reads. Small enough to bail
# quickly when the cap is exceeded, large enough not to thrash.
_UPLOAD_CHUNK_BYTES = 1 * 1024 * 1024  # 1 MB


class APIError(RuntimeError):
    """Raised when the API module can't start."""


def _resolve_max_upload_bytes() -> int:
    """Resolve the max upload size from the environment or default."""
    raw = os.environ.get(ENV_MAX_UPLOAD_BYTES)
    if not raw:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; falling back to default %d",
            ENV_MAX_UPLOAD_BYTES,
            raw,
            DEFAULT_MAX_UPLOAD_BYTES,
        )
        return DEFAULT_MAX_UPLOAD_BYTES
    if value <= 0:
        return DEFAULT_MAX_UPLOAD_BYTES
    return value


def _safe_basename(filename: Optional[str]) -> str:
    """Return only the basename of a caller-supplied filename.

    Caller-supplied filenames may include path components ("../"),
    null bytes, or be entirely absent. We never trust any of that
    - only the final path segment is used, and only to choose the
    tempfile suffix.
    """
    if not filename:
        return "upload"
    return Path(filename).name or "upload"


def _allowed_suffix(name: str) -> bool:
    """Return whether a filename has an allowed input extension."""
    suffix = Path(name).suffix
    if not suffix:
        return False
    allowed = {ext.lower() for ext in InputValidator.ALLOWED_INPUT_EXTENSIONS}
    return suffix.lower() in allowed


class _IngestLimits:
    """Bound admitted request bodies before a multipart parser can spool them.

    Limits are per application process. A disk-backed buffer avoids retaining
    all admitted bodies in memory. The extra copy trades disk I/O for a bound
    that also covers malformed multipart bodies and missing Content-Length.
    """

    def __init__(
        self,
        app: Any,
        *,
        max_body_bytes: int,
        max_concurrent: int,
        upload_timeout: float,
    ) -> None:
        """Configure per-process admission, body size and receive deadline."""
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_concurrent = max_concurrent
        self.upload_timeout = upload_timeout
        self.active = 0

    async def _reject(self, send: Any, status: int, error: str) -> None:
        """Send a small JSON error without invoking the downstream parser."""
        body = json.dumps({"error": error}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _check_content_length(
        self, headers: list[tuple[bytes, bytes]], send: Any
    ) -> bool:
        """Validate the Content-Length header against the body size limit."""
        lengths = [
            value for key, value in headers if key.lower() == b"content-length"
        ]
        if not lengths:
            return True
        if len(lengths) != 1 or not lengths[0].isdigit():
            await self._reject(send, 400, "invalid Content-Length")
            return False
        declared = lengths[0].lstrip(b"0") or b"0"
        limit = str(self.max_body_bytes).encode()
        if (len(declared), declared) > (len(limit), limit):
            await self._reject(send, 413, "request body exceeds maximum size")
            return False
        return True

    async def _buffer_body(
        self, receive: Any, send: Any, body: Any, deadline: float
    ) -> int | None:
        """Buffer incoming chunks to body. Returns byte count, or None on abort."""
        total = 0
        while True:
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            try:
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except asyncio.TimeoutError:
                await self._reject(send, 408, "upload deadline exceeded")
                return None
            if message["type"] == "http.disconnect":
                return None
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_body_bytes:
                await self._reject(
                    send, 413, "request body exceeds maximum size"
                )
                return None
            body.write(chunk)
            if not message.get("more_body", False):
                break
        return total

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """Admit, buffer and replay one bounded ingestion request."""
        path = scope.get("path", "").removeprefix(scope.get("root_path", ""))
        if (scope["type"], scope.get("method"), path) != (
            "http",
            "POST",
            "/ingest",
        ):
            await self.app(scope, receive, send)
            return
        if self.active >= self.max_concurrent:
            await self._reject(send, 503, "ingestion capacity exhausted")
            return
        self.active += 1
        try:
            if not await self._check_content_length(
                scope.get("headers", []), send
            ):
                return
            deadline = asyncio.get_running_loop().time() + self.upload_timeout
            with tempfile.TemporaryFile() as body:
                total = await self._buffer_body(receive, send, body, deadline)
                if total is None:
                    return
                body.seek(0)
                remaining = total
                delivered = False

                async def replay() -> Any:
                    """Replay the validated body in bounded chunks."""
                    nonlocal remaining, delivered
                    if delivered and remaining == 0:
                        return await receive()
                    delivered = True
                    import sys

                    api_mod = sys.modules.get("bankstatementparser.api")
                    chunk_bytes = (
                        getattr(
                            api_mod, "_UPLOAD_CHUNK_BYTES", _UPLOAD_CHUNK_BYTES
                        )
                        if api_mod is not None
                        else _UPLOAD_CHUNK_BYTES
                    )
                    chunk = body.read(chunk_bytes)
                    remaining -= len(chunk)
                    return {
                        "type": "http.request",
                        "body": chunk,
                        "more_body": remaining > 0,
                    }

                await self.app(scope, replay, send)
        finally:
            self.active -= 1
