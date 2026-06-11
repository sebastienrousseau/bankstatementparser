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
  This stops a single curl from OOM-ing the worker.
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

from __future__ import annotations

import logging
import os
import tempfile
import uuid
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
    suffix = Path(name).suffix
    if not suffix:
        return False
    allowed = {ext.lower() for ext in InputValidator.ALLOWED_INPUT_EXTENSIONS}
    return suffix.lower() in allowed


def create_app(
    *,
    title: str = "Bank Statement Parser API",
    version: str = "0.1.0",
    max_upload_bytes: Optional[int] = None,
) -> Any:
    """Create a FastAPI application wrapping :func:`smart_ingest`.

    Args:
        title: API title surfaced in the OpenAPI document.
        version: API version surfaced in the OpenAPI document and
            the ``/health`` endpoint.
        max_upload_bytes: Override the upload size cap. When
            ``None``, falls back to ``BSP_API_MAX_UPLOAD_BYTES``
            then :data:`DEFAULT_MAX_UPLOAD_BYTES`.

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

    from .hybrid import smart_ingest

    upload_cap = (
        max_upload_bytes
        if max_upload_bytes is not None
        else _resolve_max_upload_bytes()
    )

    app = FastAPI(title=title, version=version)

    _file_field = File(...)

    @app.post("/ingest")  # type: ignore[untyped-decorator]
    async def ingest(  # pragma: no cover - async endpoint needs ASGI server
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
            * ``413`` — upload exceeded ``MAX_UPLOAD_BYTES``.
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
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            total = 0
            try:
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
            finally:
                # Defensive: ensure handle is closed before
                # smart_ingest opens the path on Windows.
                tmp.flush()

        try:
            result = smart_ingest(tmp_path)
            return JSONResponse(
                content=_result_to_dict(result),
                status_code=200,
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
            Path(tmp_path).unlink(missing_ok=True)

    @app.get("/health")  # type: ignore[untyped-decorator]
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok", "version": version}

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
    if v is None:
        return None
    return {
        "status": v.status.value,
        "opening_balance": str(v.opening_balance)
        if v.opening_balance is not None
        else None,
        "closing_balance": str(v.closing_balance)
        if v.closing_balance is not None
        else None,
        "total_credits": str(v.total_credits),
        "total_debits": str(v.total_debits),
        "discrepancy": str(v.discrepancy)
        if v.discrepancy is not None
        else None,
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

    app = create_app()  # pragma: no cover - server entrypoint
    uvicorn.run(app, host=args.host, port=args.port)  # pragma: no cover
