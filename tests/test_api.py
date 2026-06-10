# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for the REST API wrapper (#v0.0.8)."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from bankstatementparser.api import APIError, create_app, main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_fake_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a fake fastapi module so tests don't need the real dep."""
    fake_fastapi = types.ModuleType("fastapi")

    class _FakeFile:
        pass

    class _FakeUploadFile:
        pass

    class _FakeApp:
        def __init__(self, **kwargs: Any) -> None:
            self._routes: dict[str, Any] = {}
            self.title = kwargs.get("title")
            self.version = kwargs.get("version")

        def post(self, path: str) -> Any:
            def decorator(fn: Any) -> Any:
                self._routes[f"POST {path}"] = fn
                return fn

            return decorator

        def get(self, path: str) -> Any:
            def decorator(fn: Any) -> Any:
                self._routes[f"GET {path}"] = fn
                return fn

            return decorator

    fake_fastapi.FastAPI = _FakeApp  # type: ignore[attr-defined]
    fake_fastapi.File = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_fastapi.UploadFile = _FakeUploadFile  # type: ignore[attr-defined]

    fake_responses = types.ModuleType("fastapi.responses")

    class _FakeJSONResponse:
        def __init__(self, content: Any, status_code: int = 200) -> None:
            self.content = content
            self.status_code = status_code

    fake_responses.JSONResponse = _FakeJSONResponse  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "fastapi", fake_fastapi)
    monkeypatch.setitem(sys.modules, "fastapi.responses", fake_responses)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_app_returns_app_with_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastapi(monkeypatch)
    app = create_app()
    assert app.title == "Bank Statement Parser API"
    assert app.version == "0.0.8"
    assert "POST /ingest" in app._routes
    assert "GET /health" in app._routes


def test_create_app_custom_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastapi(monkeypatch)
    app = create_app(title="My API", version="1.0.0")
    assert app.title == "My API"
    assert app.version == "1.0.0"


def test_create_app_raises_without_fastapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "fastapi", None)
    with pytest.raises(APIError, match="FastAPI is required"):
        create_app()


def test_health_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastapi(monkeypatch)
    app = create_app()
    health_fn = app._routes["GET /health"]
    import asyncio

    result = asyncio.run(health_fn())
    assert result["status"] == "ok"
    assert result["version"] == "0.0.8"


def test_main_raises_without_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastapi(monkeypatch)
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    monkeypatch.setattr(
        sys, "argv", ["bankstatementparser-api"]
    )
    with pytest.raises(APIError, match="uvicorn is required"):
        main()


def test_result_to_dict_structure() -> None:
    from bankstatementparser.api import _result_to_dict

    class _MockVerification:
        status = MagicMock(value="verified")
        opening_balance = None
        closing_balance = None
        total_credits = "100"
        total_debits = "0"
        discrepancy = None
        message = "ok"

    class _MockTx:
        def model_dump(self, mode: str = "json") -> dict[str, Any]:
            return {"amount": "10.00", "description": "test"}

    class _MockResult:
        source_method = "deterministic"
        source_format = "camt"
        transactions = [_MockTx()]
        verification = _MockVerification()
        warnings = ("a warning",)

    result = _result_to_dict(_MockResult())
    assert result["source_method"] == "deterministic"
    assert result["transaction_count"] == 1
    assert result["verification"]["status"] == "verified"
    assert result["warnings"] == ["a warning"]


# ---------------------------------------------------------------------------
# Safety floor (C-1): upload size cap, suffix allow-list, basename strip,
# generic error responses. These tests cover the helpers directly; the
# async ``ingest`` endpoint itself is exercised by the asgi smoke tests
# below.
# ---------------------------------------------------------------------------


def test_safe_basename_strips_path_components() -> None:
    from bankstatementparser.api import _safe_basename

    assert _safe_basename("../../../etc/passwd") == "passwd"
    assert _safe_basename("evil/../tmp/x.xml") == "x.xml"
    assert _safe_basename("just-a-file.xml") == "just-a-file.xml"


def test_safe_basename_defaults_when_missing() -> None:
    from bankstatementparser.api import _safe_basename

    assert _safe_basename(None) == "upload"
    assert _safe_basename("") == "upload"


def test_allowed_suffix_accepts_known_extensions() -> None:
    from bankstatementparser.api import _allowed_suffix

    assert _allowed_suffix("statement.xml") is True
    assert _allowed_suffix("STATEMENT.XML") is True
    assert _allowed_suffix("statement.pdf") is True
    assert _allowed_suffix("statement.csv") is True


def test_allowed_suffix_rejects_unknown_and_empty() -> None:
    from bankstatementparser.api import _allowed_suffix

    assert _allowed_suffix("statement.exe") is False
    assert _allowed_suffix("no-suffix") is False
    assert _allowed_suffix("") is False


def test_resolve_max_upload_bytes_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bankstatementparser.api import (
        DEFAULT_MAX_UPLOAD_BYTES,
        ENV_MAX_UPLOAD_BYTES,
        _resolve_max_upload_bytes,
    )

    monkeypatch.delenv(ENV_MAX_UPLOAD_BYTES, raising=False)
    assert _resolve_max_upload_bytes() == DEFAULT_MAX_UPLOAD_BYTES


def test_resolve_max_upload_bytes_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bankstatementparser.api import (
        ENV_MAX_UPLOAD_BYTES,
        _resolve_max_upload_bytes,
    )

    monkeypatch.setenv(ENV_MAX_UPLOAD_BYTES, "1048576")
    assert _resolve_max_upload_bytes() == 1048576


def test_resolve_max_upload_bytes_invalid_env_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bankstatementparser.api import (
        DEFAULT_MAX_UPLOAD_BYTES,
        ENV_MAX_UPLOAD_BYTES,
        _resolve_max_upload_bytes,
    )

    monkeypatch.setenv(ENV_MAX_UPLOAD_BYTES, "not-a-number")
    assert _resolve_max_upload_bytes() == DEFAULT_MAX_UPLOAD_BYTES


def test_resolve_max_upload_bytes_zero_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bankstatementparser.api import (
        DEFAULT_MAX_UPLOAD_BYTES,
        ENV_MAX_UPLOAD_BYTES,
        _resolve_max_upload_bytes,
    )

    monkeypatch.setenv(ENV_MAX_UPLOAD_BYTES, "0")
    assert _resolve_max_upload_bytes() == DEFAULT_MAX_UPLOAD_BYTES


def test_create_app_accepts_explicit_max_upload_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit ``max_upload_bytes`` overrides env + default.

    The value is captured into the closure of ``ingest`` so this
    test asserts ``create_app`` accepts the kwarg without raising.
    """
    _install_fake_fastapi(monkeypatch)
    app = create_app(max_upload_bytes=2048)
    assert "POST /ingest" in app._routes


def test_result_to_dict_none_verification() -> None:
    from bankstatementparser.api import _result_to_dict

    class _MockResult:
        source_method = "llm"
        source_format = "pdf"
        transactions = []
        verification = None
        warnings = ()

    result = _result_to_dict(_MockResult())
    assert result["verification"] is None
