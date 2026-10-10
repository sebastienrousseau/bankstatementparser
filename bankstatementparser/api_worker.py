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

"""Worker process execution and result serialization for the REST API."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Any, Optional, cast

from .api_limits import APIError

__all__ = [
    "PersistentWorkerPool",
    "_ingest_in_process",
    "_ingest_in_thread",
    "_reap_worker",
    "_result_to_dict",
    "_run_ingest_worker",
    "_run_worker_job",
    "_verification_dict",
]


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


def _run_ingest_worker(input_path: str, output_path: str) -> None:
    """Run one ingestion in a disposable interpreter and write its JSON result."""
    from .hybrid import smart_ingest
    from .telemetry import trace_span

    with trace_span(
        "bankstatementparser.api.worker", {"input_path": input_path}
    ):
        payload = _result_to_dict(smart_ingest(input_path))
        with open(output_path, "w", encoding="utf-8") as output:
            json.dump(payload, output)


def _run_worker_job(input_path: str) -> dict[str, Any]:
    """Execute ingestion in a warm process worker and serialize to dict."""
    from .hybrid import smart_ingest
    from .telemetry import trace_span

    with trace_span(
        "bankstatementparser.api.worker_pool", {"input_path": input_path}
    ):
        return _result_to_dict(smart_ingest(input_path))


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
        worker.exception()
        raise asyncio.CancelledError
    return worker.result()


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
                    "-I",
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


class PersistentWorkerPool:
    """Persistent warm process pool with memory recycling and execution deadlines."""

    def __init__(
        self,
        max_workers: int = 4,
        max_tasks_per_child: int = 50,
    ) -> None:
        """Initialize worker pool with concurrency and memory recycling bounds."""
        self._max_workers = max_workers
        self._max_tasks_per_child = max_tasks_per_child
        self._executor: ProcessPoolExecutor | None = None

    @property
    def is_running(self) -> bool:
        """Check whether the process pool is currently initialized and active."""
        return self._executor is not None

    def start(self) -> None:
        """Initialize the persistent worker pool if not already running."""
        if self._executor is None:
            kwargs: dict[str, Any] = {}
            if sys.version_info >= (3, 11) and self._max_tasks_per_child:
                kwargs["max_tasks_per_child"] = self._max_tasks_per_child
            self._executor = ProcessPoolExecutor(
                max_workers=self._max_workers,
                **kwargs,
            )

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the pool and release worker processes."""
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=True)
            self._executor = None

    async def run_ingest(self, path: str, timeout: float) -> dict[str, Any]:
        """Execute statement ingestion in a warm worker under an execution deadline."""
        if self._executor is None:
            self.start()
        executor = self._executor
        if executor is None:
            raise APIError("Worker pool failed to initialize")
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(executor, _run_worker_job, path)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            raise APIError(f"Worker ingestion failed: {exc}") from exc
