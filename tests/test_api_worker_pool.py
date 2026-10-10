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

"""Tests for PersistentWorkerPool and worker pool API integration."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from bankstatementparser.api import APIError, PersistentWorkerPool, create_app
from bankstatementparser.api_worker import _run_worker_job


def test_persistent_worker_pool_lifecycle() -> None:
    """Verify pool initialization, start, property, and shutdown states."""
    pool = PersistentWorkerPool(max_workers=2, max_tasks_per_child=10)
    assert not pool.is_running

    pool.start()
    assert pool.is_running

    # Repeated start is idempotent
    pool.start()
    assert pool.is_running

    pool.shutdown(wait=True)
    assert not pool.is_running

    # Repeated shutdown is idempotent
    pool.shutdown()
    assert not pool.is_running


def test_persistent_worker_pool_run_ingest_success() -> None:
    """Verify run_ingest successfully awaits executor future."""
    pool = PersistentWorkerPool(max_workers=1)

    async def exercise() -> None:
        mock_future = asyncio.Future()
        mock_future.set_result({"transaction_count": 5})

        with patch.object(
            asyncio.get_running_loop(),
            "run_in_executor",
            return_value=mock_future,
        ):
            res1 = await pool.run_ingest("dummy.csv", timeout=2.0)
            assert res1 == {"transaction_count": 5}
            assert pool.is_running

            # Second call when pool is already started
            res2 = await pool.run_ingest("dummy.csv", timeout=2.0)
            assert res2 == {"transaction_count": 5}

    asyncio.run(exercise())
    pool.shutdown()

    # Test pool with max_tasks_per_child=0
    pool_zero = PersistentWorkerPool(max_workers=1, max_tasks_per_child=0)
    pool_zero.start()
    pool_zero.shutdown()


def test_persistent_worker_pool_run_ingest_timeout() -> None:
    """Verify run_ingest raises asyncio.TimeoutError on deadline expiry."""
    pool = PersistentWorkerPool(max_workers=1)

    async def exercise() -> None:
        never_done: asyncio.Future[dict[str, object]] = asyncio.Future()

        with patch.object(
            asyncio.get_running_loop(),
            "run_in_executor",
            return_value=never_done,
        ):
            with pytest.raises(asyncio.TimeoutError):
                await pool.run_ingest("dummy.csv", timeout=0.01)

    asyncio.run(exercise())
    pool.shutdown()


def test_persistent_worker_pool_run_ingest_error() -> None:
    """Verify errors inside the worker process wrap in APIError."""
    pool = PersistentWorkerPool(max_workers=1)

    async def exercise() -> None:
        failed_future = asyncio.Future()
        failed_future.set_exception(RuntimeError("worker crashed"))

        with patch.object(
            asyncio.get_running_loop(),
            "run_in_executor",
            return_value=failed_future,
        ):
            with pytest.raises(APIError, match="Worker ingestion failed"):
                await pool.run_ingest("dummy.csv", timeout=2.0)

    asyncio.run(exercise())
    pool.shutdown()


def test_persistent_worker_pool_start_failure() -> None:
    """Verify APIError raised if executor fails to initialize."""
    pool = PersistentWorkerPool(max_workers=1)

    async def exercise() -> None:
        with patch.object(pool, "start"):
            with pytest.raises(APIError, match="failed to initialize"):
                await pool.run_ingest("dummy.csv", timeout=2.0)

    asyncio.run(exercise())


def test_run_worker_job() -> None:
    """Verify _run_worker_job calls smart_ingest and serializes to dict."""
    with patch("bankstatementparser.hybrid.smart_ingest") as mock_ingest:
        mock_result = MagicMock()
        mock_result.source_method = "deterministic"
        mock_result.source_format = "csv"
        mock_result.transactions = []
        mock_result.verification = None
        mock_result.warnings = []
        mock_ingest.return_value = mock_result

        out = _run_worker_job("sample.csv")
        assert out["source_method"] == "deterministic"
        assert out["transaction_count"] == 0


def test_ingest_route_with_worker_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify create_app dispatches to worker_pool.run_ingest when provided."""
    import sys
    import types

    fake_fastapi = types.ModuleType("fastapi")

    class _FakeApp:
        def __init__(self, **kwargs: object) -> None:
            self._routes: dict[str, object] = {}

        def add_middleware(self, *args: object, **kwargs: object) -> None:
            pass

        def post(self, path: str) -> object:
            def dec(fn: object) -> object:
                self._routes[f"POST {path}"] = fn
                return fn

            return dec

        def get(self, path: str) -> object:
            def dec(fn: object) -> object:
                self._routes[f"GET {path}"] = fn
                return fn

            return dec

    fake_fastapi.FastAPI = _FakeApp  # type: ignore[attr-defined]
    fake_fastapi.File = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_fastapi.UploadFile = MagicMock  # type: ignore[attr-defined]

    fake_responses = types.ModuleType("fastapi.responses")

    class _FakeJSONResponse:
        def __init__(self, content: object, status_code: int = 200) -> None:
            self.content = content
            self.status_code = status_code

    fake_responses.JSONResponse = _FakeJSONResponse  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "fastapi", fake_fastapi)
    monkeypatch.setitem(sys.modules, "fastapi.responses", fake_responses)

    mock_pool = MagicMock(spec=PersistentWorkerPool)

    async def mock_run_ingest(path: str, timeout: float) -> dict[str, object]:
        return {"transaction_count": 3}

    mock_pool.run_ingest = mock_run_ingest

    app = create_app(worker_pool=mock_pool, ingest_timeout=10.0)
    handler = app._routes["POST /ingest"]

    mock_upload = MagicMock()
    mock_upload.filename = "test.csv"

    async def read_mock(size: int) -> bytes:
        if not hasattr(read_mock, "called"):
            read_mock.called = True
            return b"amount\n100\n"
        return b""

    mock_upload.read = read_mock

    response = asyncio.run(handler(mock_upload))
    assert response.status_code == 200
    assert response.content == {"transaction_count": 3}
