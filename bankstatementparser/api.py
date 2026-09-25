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

"""Lightweight REST API for the hybrid pipeline.

Finance teams want to POST a file and get JSON back. This module
wraps :func:`smart_ingest` in a single-file FastAPI app that can be
run as a microservice:

    pip install 'bankstatementparser[api]'
    bankstatementparser-api              # starts on :8000
    bankstatementparser-api --port 9000  # custom port

Or import the app for ASGI deployment::

    from bankstatementparser.api import create_app

    app = create_app()
    # uvicorn bankstatementparser.api:app --host 0.0.0.0

Security defaults
-----------------

The API is **stateless** — each ``/ingest`` call processes the
uploaded file and returns the result as JSON. The minimum safety
floor enforced here:

* Uploads are read in chunks; the request is rejected with HTTP
  413 once the cumulative size exceeds :data:`MAX_UPLOAD_BYTES`
  (default 25 MB, overridable via ``BSP_API_MAX_UPLOAD_BYTES``).
  A raw request-body limit (file cap plus 64 KiB multipart overhead)
  is enforced before multipart decoding, including chunked uploads.
* At most four ingestion requests are admitted per application process;
  excess requests receive HTTP 503. Request bodies have a 60-second receive
  deadline. Ingestion runs in a disposable process with a 120-second execution
  deadline, including startup. Timeout or cancellation kills and reaps that
  process before releasing its slot or input file. Configure via ``create_app``.
  Explicit ``ingest_timeout=None`` retains the legacy thread mode, which waits
  for ingestion to finish on cancellation and has no execution deadline.
* The uploaded filename is reduced to its basename — never trust
  caller-supplied path components — and the suffix is matched
  against :data:`InputValidator.ALLOWED_INPUT_EXTENSIONS` before
  any work is done.
* Exceptions raised by ``smart_ingest`` are logged with a UUID
  correlation id and the client receives a generic 422 response
  that does **not** echo the raw exception message (which could
  leak filesystem paths).

Authentication, authorisation, and rate limiting are **not**
implemented here by design — they belong in the reverse proxy or
API gateway in front of this service (nginx ``limit_req``,
``auth_basic``; or a dedicated WAF). The default bind is
``127.0.0.1`` so a fresh ``bankstatementparser-api`` is never
publicly reachable unless explicitly opted in.

Gated behind the ``[api]`` install extra (fastapi + uvicorn).
"""

import asyncio
import json
import logging
import math
import os
import sys
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Optional, cast

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
    — only the final path segment is used, and only to choose the
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
            lengths = [
                value
                for key, value in scope.get("headers", [])
                if key.lower() == b"content-length"
            ]
            if lengths:
                if len(lengths) != 1 or not lengths[0].isdigit():
                    await self._reject(send, 400, "invalid Content-Length")
                    return
                declared = lengths[0].lstrip(b"0") or b"0"
                limit = str(self.max_body_bytes).encode()
                if (len(declared), declared) > (len(limit), limit):
                    await self._reject(
                        send, 413, "request body exceeds maximum size"
                    )
                    return
            deadline = asyncio.get_running_loop().time() + self.upload_timeout
            with tempfile.TemporaryFile() as body:
                total = 0
                while True:
                    try:
                        message = await asyncio.wait_for(
                            receive(),
                            timeout=max(
                                0, deadline - asyncio.get_running_loop().time()
                            ),
                        )
                    except asyncio.TimeoutError:
                        await self._reject(
                            send, 408, "upload deadline exceeded"
                        )
                        return
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    total += len(chunk)
                    if total > self.max_body_bytes:
                        await self._reject(
                            send, 413, "request body exceeds maximum size"
                        )
                        return
                    body.write(chunk)
                    if not message.get("more_body", False):
                        break
                body.seek(0)
                remaining = total
                delivered = False

                async def replay() -> Any:
                    """Replay the validated body in bounded chunks."""
                    nonlocal remaining, delivered
                    if delivered and remaining == 0:
                        return await receive()
                    delivered = True
                    chunk = body.read(_UPLOAD_CHUNK_BYTES)
                    remaining -= len(chunk)
                    return {
                        "type": "http.request",
                        "body": chunk,
                        "more_body": remaining > 0,
                    }

                await self.app(scope, replay, send)
        finally:
            self.active -= 1


async def _ingest_in_thread(ingest: Any, path: str) -> Any:
    """Keep the input and admission slot alive until a cancelled worker exits.

    Python cannot stop a running thread. Shielding and draining it prevents
    cancellation from releasing capacity while ingestion is still running.
    A hard execution deadline requires a separately supervised process.
    """
    worker = asyncio.create_task(asyncio.to_thread(ingest, path))
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        # Retrieve exceptions even when the caller no longer needs a result.
        worker.exception()
        raise asyncio.CancelledError
    return worker.result()


def _run_ingest_worker(input_path: str, output_path: str) -> None:
    """Run one ingestion in a disposable interpreter and write its JSON result."""
    from .hybrid import smart_ingest

    payload = _result_to_dict(smart_ingest(input_path))
    with open(output_path, "w", encoding="utf-8") as output:
        json.dump(payload, output)


async def _reap_worker(process: asyncio.subprocess.Process) -> None:
    """Wait for process exit even if cleanup receives repeated cancellation."""
    waiter = asyncio.create_task(process.wait())
    cancelled = False
    while not waiter.done():
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError:
            cancelled = True
    waiter.result()
    if cancelled:
        raise asyncio.CancelledError


async def _ingest_in_process(path: str, timeout: float) -> dict[str, Any]:
    """Enforce an ingestion deadline and reap the worker before input cleanup."""
    process = None
    deadline = asyncio.get_running_loop().time() + timeout
    with tempfile.TemporaryDirectory(prefix="bsp_worker_") as directory:
        output_path = str(Path(directory) / "result.json")
        try:
            process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    sys.executable,
                    "-c",
                    "import sys; from bankstatementparser.api import _run_ingest_worker; "
                    "_run_ingest_worker(sys.argv[1], sys.argv[2])",
                    path,
                    output_path,
                    stdout=asyncio.subprocess.DEVNULL,
                ),
                timeout=timeout,
            )
            await asyncio.wait_for(
                process.wait(),
                timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
            )
            if process.returncode != 0:
                raise APIError(
                    f"Ingestion worker exited with status {process.returncode}"
                )
            with open(output_path, encoding="utf-8") as output:
                return cast(dict[str, Any], json.load(output))
        finally:
            if process is not None:
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
                await _reap_worker(process)


def create_app(
    *,
    title: str = "Bank Statement Parser API",
    version: Optional[str] = None,
    max_upload_bytes: Optional[int] = None,
    max_concurrent_ingests: int = 4,
    upload_timeout: float = 60.0,
    ingest_timeout: float | None = 120.0,
) -> Any:
    """Create a FastAPI application wrapping :func:`smart_ingest`.

    Args:
        title: API title surfaced in the OpenAPI document.
        version: API version surfaced in the OpenAPI document and
            the ``/health`` endpoint.
        max_upload_bytes: Override the upload size cap. When
            ``None``, falls back to ``BSP_API_MAX_UPLOAD_BYTES``
            then :data:`DEFAULT_MAX_UPLOAD_BYTES`.
        max_concurrent_ingests: Maximum admitted uploads and ingestion jobs
            per application process; excess requests receive HTTP 503.
        upload_timeout: Seconds allowed to receive the entire request body.
            Separate from the ingestion execution deadline.
        ingest_timeout: Execution deadline in seconds, including worker startup.
            The default isolates ingestion in a disposable Python process.
            None opts into the legacy thread worker without an execution limit.

    Returns:
        A FastAPI ``app`` instance. Raises :class:`APIError` if
        FastAPI is not installed.
    """
    try:
        from fastapi import FastAPI, File, UploadFile
        from fastapi.responses import JSONResponse
    except ImportError as exc:
        raise APIError(
            "FastAPI is required for the REST API. "
            "Install with: pip install 'bankstatementparser[api]'"
        ) from exc

    from . import __version__
    from .hybrid import smart_ingest

    resolved_version = version or __version__

    upload_cap = (
        max_upload_bytes
        if max_upload_bytes is not None
        else _resolve_max_upload_bytes()
    )

    if (
        upload_cap <= 0
        or max_concurrent_ingests <= 0
        or upload_timeout <= 0
        or not math.isfinite(upload_timeout)
        or (
            ingest_timeout is not None
            and (ingest_timeout <= 0 or not math.isfinite(ingest_timeout))
        )
    ):
        raise ValueError("API resource limits must be positive")

    app = FastAPI(title=title, version=resolved_version)
    app.add_middleware(
        _IngestLimits,
        max_body_bytes=upload_cap + 64 * 1024,
        max_concurrent=max_concurrent_ingests,
        upload_timeout=upload_timeout,
    )

    _file_field = File(...)

    @app.post("/ingest")  # type: ignore[untyped-decorator]
    async def ingest(
        file: UploadFile = _file_field,
    ) -> JSONResponse:
        """Upload a bank statement and get structured JSON back.

        Accepts any format declared in
        :data:`InputValidator.ALLOWED_INPUT_EXTENSIONS`. The
        routing inside :func:`smart_ingest` is automatic —
        deterministic parsers run first, LLM fallback for PDFs.

        Returns the full :class:`IngestResult` as JSON including
        transactions, verification status, and warnings.

        Responses:
            * ``200`` — parse succeeded.
            * ``400`` — disallowed extension.
            * ``408`` — request-body receive deadline exceeded.
            * ``413`` — upload or raw request body exceeded its cap.
            * ``503`` — ingestion admission capacity exhausted.
            * ``504`` — ingestion worker exceeded its execution deadline.
            * ``422`` — parse failed; response carries a correlation
              id, the raw error is logged server-side only.
        """
        safe_name = _safe_basename(file.filename)
        if not _allowed_suffix(safe_name):
            return JSONResponse(
                content={
                    "error": "unsupported file extension",
                    "allowed_extensions": sorted(
                        {
                            ext.lower()
                            for ext in InputValidator.ALLOWED_INPUT_EXTENSIONS
                        }
                    ),
                },
                status_code=400,
            )

        suffix = Path(safe_name).suffix
        # ``delete=False`` so we can close, hand the path to
        # ``smart_ingest``, then unlink in the ``finally`` block.
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False
            ) as tmp:
                tmp_path = tmp.name
                total = 0
                while True:
                    chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > upload_cap:
                        return JSONResponse(
                            content={
                                "error": "upload exceeds maximum size",
                                "max_upload_bytes": upload_cap,
                            },
                            status_code=413,
                        )
                    tmp.write(chunk)
                # Defensive: ensure handle is closed before
                # smart_ingest opens the path on Windows.
                tmp.flush()
            if ingest_timeout is None:
                payload = _result_to_dict(
                    await _ingest_in_thread(smart_ingest, tmp_path)
                )
            else:
                payload = await _ingest_in_process(tmp_path, ingest_timeout)
            return JSONResponse(content=payload, status_code=200)
        except asyncio.TimeoutError:
            return JSONResponse(
                content={"error": "ingest execution deadline exceeded"},
                status_code=504,
            )
        except Exception as exc:
            correlation_id = uuid.uuid4().hex
            # Log the raw exception (with stack) server-side only;
            # the client gets a correlation id, not the message —
            # preventing accidental disclosure of filesystem paths
            # or upstream service URLs.
            logger.exception("Ingest failed [%s]: %s", correlation_id, exc)
            return JSONResponse(
                content={
                    "error": "ingest failed",
                    "correlation_id": correlation_id,
                },
                status_code=422,
            )
        finally:
            if tmp_path is not None:
                Path(tmp_path).unlink(missing_ok=True)

    @app.get("/health")  # type: ignore[untyped-decorator]
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok", "version": resolved_version}

    return app


def _result_to_dict(result: Any) -> dict[str, Any]:
    """Serialize an IngestResult to a JSON-safe dict."""
    return {
        "source_method": result.source_method,
        "source_format": result.source_format,
        "transaction_count": len(result.transactions),
        "transactions": [
            tx.model_dump(mode="json") for tx in result.transactions
        ],
        "verification": _verification_dict(result.verification),
        "warnings": list(result.warnings),
    }


def _verification_dict(v: Any) -> Optional[dict[str, Any]]:
    """Serialize a verification result to a JSON-safe dict, or None."""
    if v is None:
        return None
    return {
        "status": v.status.value,
        "opening_balance": (
            str(v.opening_balance) if v.opening_balance is not None else None
        ),
        "closing_balance": (
            str(v.closing_balance) if v.closing_balance is not None else None
        ),
        "total_credits": str(v.total_credits),
        "total_debits": str(v.total_debits),
        "discrepancy": (
            str(v.discrepancy) if v.discrepancy is not None else None
        ),
        "message": v.message,
    }


def main() -> None:
    """Console-script entry point for ``bankstatementparser-api``."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Start the Bank Statement Parser REST API."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (use 0.0.0.0 for container deployments)",
    )
    parser.add_argument("--port", type=int, default=8000, help="Port")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as exc:
        raise APIError(
            "uvicorn is required to run the API server. "
            "Install with: pip install 'bankstatementparser[api]'"
        ) from exc

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)
