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
"""

from __future__ import annotations

import asyncio
import logging
import math
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .api_limits import (
    _UPLOAD_CHUNK_BYTES,
    DEFAULT_MAX_UPLOAD_BYTES,
    ENV_MAX_UPLOAD_BYTES,
    APIError,
    _allowed_suffix,
    _IngestLimits,
    _resolve_max_upload_bytes,
    _safe_basename,
)
from .api_worker import (
    _ingest_in_process,
    _ingest_in_thread,
    _reap_worker,
    _result_to_dict,
    _run_ingest_worker,
    _verification_dict,
)
from .input_validator import InputValidator
from .telemetry import trace_span

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MAX_UPLOAD_BYTES",
    "ENV_MAX_UPLOAD_BYTES",
    "_UPLOAD_CHUNK_BYTES",
    "APIError",
    "_IngestLimits",
    "_allowed_suffix",
    "_ingest_in_process",
    "_ingest_in_thread",
    "_reap_worker",
    "_resolve_max_upload_bytes",
    "_result_to_dict",
    "_run_ingest_worker",
    "_safe_basename",
    "_verification_dict",
    "create_app",
    "main",
]


async def _spool_upload_file(file: Any, tmp: Any, max_upload: int) -> bool:
    """Spool chunks to temporary file, returning False if max_upload exceeded."""
    total = 0
    while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
        total += len(chunk)
        if total > max_upload:
            return False
        tmp.write(chunk)
    tmp.flush()
    return True


def _build_ingest_handler(
    app: Any,
    max_upload: int,
    ingest_timeout: float | None,
) -> Any:
    """Register the POST /ingest endpoint on the FastAPI application."""
    from fastapi import File, UploadFile
    from fastapi.responses import JSONResponse

    from .hybrid import smart_ingest

    _file_field = File(...)

    @app.post("/ingest")  # type: ignore[untyped-decorator]
    async def ingest(
        file: UploadFile = _file_field,  # type: ignore[assignment]
    ) -> Any:
        """Ingest a bank statement file and return extracted transactions."""
        safe_name = _safe_basename(file.filename)
        with trace_span(
            "bankstatementparser.api.ingest", {"filename": safe_name}
        ):
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
            tmp_path: Optional[str] = None
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=suffix, delete=False
                ) as tmp:
                    tmp_path = tmp.name
                    if not await _spool_upload_file(file, tmp, max_upload):
                        return JSONResponse(
                            content={
                                "error": "upload exceeds maximum size",
                                "max_upload_bytes": max_upload,
                            },
                            status_code=413,
                        )
                if ingest_timeout is None:
                    result = await _ingest_in_thread(smart_ingest, tmp_path)
                    payload = _result_to_dict(result)
                else:
                    payload = await _ingest_in_process(
                        tmp_path, ingest_timeout
                    )
                return JSONResponse(content=payload, status_code=200)
            except asyncio.TimeoutError:
                return JSONResponse(
                    content={"error": "ingest execution deadline exceeded"},
                    status_code=504,
                )
            except Exception as exc:
                correlation_id = uuid.uuid4().hex
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


def create_app(
    *,
    title: str = "Bank Statement Parser API",
    version: Optional[str] = None,
    max_upload_bytes: Optional[int] = None,
    max_concurrent_ingests: int = 4,
    upload_timeout: float = 60.0,
    ingest_timeout: float | None = 120.0,
) -> Any:
    """Create a FastAPI application wrapping :func:`smart_ingest`."""
    try:
        from fastapi import FastAPI
    except ImportError as exc:
        raise APIError(
            "FastAPI is required for the REST API. "
            "Install with: pip install 'bankstatementparser[api]'"
        ) from exc

    resolved_version = version if version is not None else __version__

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

    _build_ingest_handler(app, upload_cap, ingest_timeout)

    @app.get("/health")  # type: ignore[untyped-decorator]
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok", "version": resolved_version}

    return app


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
