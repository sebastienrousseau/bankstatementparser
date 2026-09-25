# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for the REST API wrapper (#v0.0.8)."""

from __future__ import annotations

import sys
import types
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

from bankstatementparser import __version__
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

        def add_middleware(self, *args: Any, **kwargs: Any) -> None:
            self.middleware = (args, kwargs)

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
    assert app.version == __version__
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
    assert result["version"] == __version__


def test_main_raises_without_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastapi(monkeypatch)
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    monkeypatch.setattr(sys, "argv", ["bankstatementparser-api"])
    with pytest.raises(APIError, match="uvicorn is required"):
        main()


def test_main_starts_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``main`` builds the app and hands it to ``uvicorn.run``."""
    _install_fake_fastapi(monkeypatch)

    captured: dict[str, Any] = {}
    fake_uvicorn = types.ModuleType("uvicorn")

    def _run(app: Any, host: str, port: int) -> None:
        captured.update(app=app, host=host, port=port)

    fake_uvicorn.run = _run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(
        sys, "argv", ["bankstatementparser-api", "--port", "9999"]
    )

    main()
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9999
    assert captured["app"] is not None


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
        transactions: ClassVar[list[Any]] = [_MockTx()]
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
# async ``ingest`` endpoint itself is exercised by the route-level tests
# at the end of this module.
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
    app = create_app(max_upload_bytes=2048, ingest_timeout=None)
    assert "POST /ingest" in app._routes


def test_result_to_dict_none_verification() -> None:
    from bankstatementparser.api import _result_to_dict

    class _MockResult:
        source_method = "llm"
        source_format = "pdf"
        transactions: ClassVar[list[Any]] = []
        verification = None
        warnings = ()

    result = _result_to_dict(_MockResult())
    assert result["verification"] is None


# ---------------------------------------------------------------------------
# The async ``/ingest`` endpoint, driven directly through the captured route
# function (the fake FastAPI app exposes it via ``app._routes``). These cover
# the bad-extension, oversize, success, and failure branches without a live
# ASGI server.
# ---------------------------------------------------------------------------


class _FakeUpload:
    """Minimal stand-in for FastAPI's ``UploadFile``."""

    def __init__(self, filename: str | None, data: bytes) -> None:
        """Store the filename and back the read() stream with *data*."""
        self.filename = filename
        self._buffer = data
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        """Return up to *size* bytes from the buffered upload."""
        if size < 0:
            chunk = self._buffer[self._pos :]
            self._pos = len(self._buffer)
            return chunk
        chunk = self._buffer[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


def _ingest_route(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> Any:
    """Build the app with a fake FastAPI and return its ``/ingest`` route."""
    _install_fake_fastapi(monkeypatch)
    kwargs.setdefault("ingest_timeout", None)
    app = create_app(**kwargs)
    return app._routes["POST /ingest"]


def test_ingest_rejects_unsupported_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    route = _ingest_route(monkeypatch)
    upload = _FakeUpload("malware.exe", b"data")
    response = asyncio.run(route(file=upload))
    assert response.status_code == 400
    assert response.content["error"] == "unsupported file extension"
    assert "allowed_extensions" in response.content


def test_ingest_rejects_oversize_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    route = _ingest_route(monkeypatch, max_upload_bytes=4)
    upload = _FakeUpload("statement.csv", b"way too many bytes")
    response = asyncio.run(route(file=upload))
    assert response.status_code == 413
    assert response.content["error"] == "upload exceeds maximum size"
    assert response.content["max_upload_bytes"] == 4


def test_ingest_success_returns_serialized_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    class _MockResult:
        source_method = "deterministic"
        source_format = "csv"
        transactions: ClassVar[list[Any]] = []
        verification = None
        warnings = ()

    import bankstatementparser.hybrid as hybrid_pkg

    monkeypatch.setattr(
        hybrid_pkg, "smart_ingest", lambda _path: _MockResult()
    )

    route = _ingest_route(monkeypatch)
    upload = _FakeUpload("statement.csv", b"date,amount\n2026-01-01,1.00\n")
    response = asyncio.run(route(file=upload))
    assert response.status_code == 200
    assert response.content["source_method"] == "deterministic"
    assert response.content["transaction_count"] == 0


def test_ingest_failure_returns_correlation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import bankstatementparser.hybrid as hybrid_pkg

    def _boom(_path: str) -> Any:
        raise RuntimeError("secret /tmp/path leaked")

    monkeypatch.setattr(hybrid_pkg, "smart_ingest", _boom)

    route = _ingest_route(monkeypatch)
    upload = _FakeUpload("statement.csv", b"date,amount\n")
    response = asyncio.run(route(file=upload))
    assert response.status_code == 422
    assert response.content["error"] == "ingest failed"
    # The raw error message must NOT leak to the client.
    assert "secret" not in str(response.content)
    assert len(response.content["correlation_id"]) == 32


@pytest.mark.parametrize(
    "limits",
    [
        {"max_upload_bytes": 0},
        {"max_concurrent_ingests": 0},
        {"upload_timeout": 0},
        {"upload_timeout": float("nan")},
        {"upload_timeout": float("inf")},
    ],
)
def test_api_rejects_invalid_limits(
    monkeypatch: pytest.MonkeyPatch, limits: dict
) -> None:
    """Invalid configuration must not silently disable resource bounds."""
    _install_fake_fastapi(monkeypatch)
    with pytest.raises(ValueError, match="positive"):
        create_app(**limits)


@pytest.mark.parametrize(
    ("headers", "chunks", "status"),
    [
        ([], [b"123", b"456"], 413),
        ([(b"content-length", b"1")], [b"123456"], 413),
        ([(b"content-length", b"6")], [], 413),
        ([(b"Content-Length", b"9" * 5000)], [], 413),
        ([(b"content-length", b"-1")], [], 400),
        ([(b"content-length", b"abc")], [], 400),
        ([(b"content-length", b"1"), (b"content-length", b"1")], [], 400),
        ([(b"content-length", b"00005")], [b"12", b"345"], 200),
        ([], [b""], 200),
    ],
)
def test_request_limits_before_parser(
    headers: list,
    chunks: list[bytes],
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Count raw chunks even without a trustworthy Content-Length header."""
    import asyncio

    from bankstatementparser.api import _IngestLimits

    monkeypatch.setattr("bankstatementparser.api._UPLOAD_CHUNK_BYTES", 2)

    async def scenario() -> None:
        events = []
        pending = list(chunks)
        reached = False

        async def receive() -> dict:
            if not pending:
                return {"type": "http.disconnect"}
            return {
                "type": "http.request",
                "body": pending.pop(0),
                "more_body": bool(pending),
            }

        async def send(message: dict) -> None:
            events.append(message)

        async def downstream(scope: dict, replay: Any, send: Any) -> None:
            nonlocal reached
            reached = True
            body = b""
            while True:
                message = await replay()
                body += message["body"]
                if not message["more_body"]:
                    break
            assert body == b"".join(chunks)
            assert (await replay())["type"] == "http.disconnect"
            await send({"type": "http.response.start", "status": 200})

        app = _IngestLimits(
            downstream, max_body_bytes=5, max_concurrent=1, upload_timeout=1
        )
        await app(
            {
                "type": "http",
                "method": "POST",
                "path": "/ingest",
                "headers": headers,
            },
            receive,
            send,
        )
        assert events[0]["status"] == status
        assert reached is (status == 200)
        assert app.active == 0

    asyncio.run(scenario())


def test_request_admission_timeout_disconnect_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health stays available under load and every exit releases admission."""
    import asyncio
    import tempfile

    from bankstatementparser.api import _IngestLimits

    opened = []
    original = tempfile.TemporaryFile

    def track_file(*args: Any, **kwargs: Any) -> Any:
        handle = original(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(tempfile, "TemporaryFile", track_file)

    async def scenario() -> None:
        events = []
        entered = asyncio.Event()
        release = asyncio.Event()
        scope = {"type": "http", "method": "POST", "path": "/ingest"}

        async def downstream(scope: dict, receive: Any, send: Any) -> None:
            if scope.get("path") == "/ingest":
                entered.set()
                await release.wait()
                raise RuntimeError("parse failure")
            await send({"status": 200})

        async def receive() -> dict:
            return {"type": "http.request", "body": b"ok"}

        async def disconnect() -> dict:
            return {"type": "http.disconnect"}

        async def stalled() -> dict:
            await asyncio.sleep(10)
            return {}

        async def send(message: dict) -> None:
            events.append(message)

        app = _IngestLimits(
            downstream, max_body_bytes=5, max_concurrent=1, upload_timeout=5
        )
        first = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(entered.wait(), timeout=5)
        await app(scope, receive, send)
        assert events[0]["status"] == 503
        await app({**scope, "path": "/health", "method": "GET"}, receive, send)
        assert events[-1]["status"] == 200
        release.set()
        with pytest.raises(RuntimeError, match="parse failure"):
            await first
        assert app.active == 0
        await app(scope, disconnect, send)
        assert app.active == 0
        events.clear()
        app.upload_timeout = 0.01
        await app(scope, stalled, send)
        assert events[0]["status"] == 408
        assert app.active == 0
        assert all(handle.closed for handle in opened)

    asyncio.run(scenario())


@pytest.mark.parametrize("fail", [False, True])
def test_cancelled_ingest_waits_for_worker(fail: bool) -> None:
    """Repeated cancellation cannot release a still-running ingestion job."""
    import asyncio
    import threading

    from bankstatementparser.api import _ingest_in_thread

    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def ingest(path: str) -> str:
            started.set()
            try:
                assert release.wait(timeout=5)
                if fail:
                    raise ValueError("worker failed")
                return path
            finally:
                finished.set()

        task = asyncio.create_task(_ingest_in_thread(ingest, "input.csv"))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(scenario())


def test_ingest_worker_serializes_result(tmp_path) -> None:
    import asyncio
    import json

    from bankstatementparser.api import _ingest_in_process, _run_ingest_worker

    source = tmp_path / "input.csv"
    source.write_text("date,amount,currency\n2026-01-01,1.23,EUR\n")
    output = tmp_path / "result.json"
    _run_ingest_worker(str(source), str(output))
    assert json.loads(output.read_text())["transaction_count"] == 1
    assert (
        asyncio.run(_ingest_in_process(str(source), 30))["transaction_count"]
        == 1
    )


@pytest.mark.parametrize("cancel", [False, True])
def test_process_deadline_and_cancellation_reap_worker(
    monkeypatch, cancel
) -> None:
    import asyncio
    from pathlib import Path

    from bankstatementparser.api import _ingest_in_process

    async def exercise():
        real_spawn = asyncio.create_subprocess_exec
        started = asyncio.Event()
        processes = []
        outputs = []

        async def spawn(*args, **kwargs):
            outputs.append(Path(args[-1]))
            process = await real_spawn(
                sys.executable, "-c", "import time; time.sleep(60)", **kwargs
            )
            processes.append(process)
            started.set()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        task = asyncio.create_task(
            _ingest_in_process("unused.csv", 10 if cancel else 2)
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(asyncio.TimeoutError):
                await task
        assert processes[0].returncode is not None
        assert not outputs[0].parent.exists()

    asyncio.run(exercise())


def test_process_worker_failure_and_spawn_failure(monkeypatch) -> None:
    import asyncio

    from bankstatementparser.api import _ingest_in_process

    async def exercise():
        real_spawn = asyncio.create_subprocess_exec

        async def fail_worker(*args, **kwargs):
            return await real_spawn(
                sys.executable, "-c", "raise SystemExit(7)", **kwargs
            )

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_worker)
        with pytest.raises(APIError, match="status 7"):
            await _ingest_in_process("unused.csv", 10)

        async def fail_spawn(*args, **kwargs):
            raise OSError("spawn failed")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_spawn)
        with pytest.raises(OSError, match="spawn failed"):
            await _ingest_in_process("unused.csv", 10)

    asyncio.run(exercise())


def test_reap_worker_survives_repeated_cancellation() -> None:
    import asyncio

    from bankstatementparser.api import _reap_worker

    async def exercise():
        release = asyncio.Event()
        entered = asyncio.Event()

        class Process:
            async def wait(self):
                entered.set()
                await release.wait()
                return 0

        task = asyncio.create_task(_reap_worker(Process()))
        await entered.wait()
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())


def test_ingest_route_execution_timeout(monkeypatch) -> None:
    import asyncio

    from bankstatementparser import api

    async def timeout(*args):
        raise asyncio.TimeoutError

    async def success(*args):
        return {"transaction_count": 1}

    monkeypatch.setattr(api, "_ingest_in_process", success)
    route = _ingest_route(monkeypatch, ingest_timeout=1)
    response = asyncio.run(route(_FakeUpload("test.csv", b"amount\n1\n")))
    assert response.status_code == 200
    assert response.content == {"transaction_count": 1}
    monkeypatch.setattr(api, "_ingest_in_process", timeout)
    response = asyncio.run(route(_FakeUpload("test.csv", b"amount\n1\n")))
    assert response.status_code == 504
    assert response.content == {"error": "ingest execution deadline exceeded"}


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_ingest_execution_limit_validation(monkeypatch, limit) -> None:
    _install_fake_fastapi(monkeypatch)
    with pytest.raises(ValueError, match="positive"):
        create_app(ingest_timeout=limit)
