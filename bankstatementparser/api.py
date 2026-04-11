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

The API is **stateless** — each ``/ingest`` call processes the
uploaded file and returns the result as JSON. No database, no
sessions, no auth (add those in your reverse proxy or wrapper).

Gated behind the ``[api]`` install extra (fastapi + uvicorn).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class APIError(RuntimeError):
    """Raised when the API module can't start."""


def create_app(
    *,
    title: str = "Bank Statement Parser API",
    version: str = "0.0.8",
) -> Any:
    """Create a FastAPI application wrapping :func:`smart_ingest`.

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

    app = FastAPI(title=title, version=version)

    _file_field = File(...)

    @app.post("/ingest")  # type: ignore[untyped-decorator]
    async def ingest(  # pragma: no cover - async endpoint needs ASGI server
        file: UploadFile = _file_field,  # noqa: B008
    ) -> JSONResponse:
        """Upload a bank statement and get structured JSON back.

        Accepts any format supported by :func:`smart_ingest`:
        CAMT, PAIN.001, CSV, OFX, QFX, MT940, or PDF. The routing
        is automatic — deterministic parsers run first, LLM
        fallback for PDFs.

        Returns the full :class:`IngestResult` as JSON including
        transactions, verification status, and warnings.
        """
        suffix = Path(file.filename or "upload").suffix or ".xml"
        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = smart_ingest(tmp_path)
            return JSONResponse(
                content=_result_to_dict(result),
                status_code=200,
            )
        except Exception as exc:
            logger.error("Ingest failed: %s", exc)
            return JSONResponse(
                content={"error": str(exc)},
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
    parser.add_argument(
        "--port", type=int, default=8000, help="Port"
    )
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
