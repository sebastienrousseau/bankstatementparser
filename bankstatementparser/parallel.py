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
#
# See the License for the specific language governing permissions and
# limitations under the License.

"""Parallel multi-file parsing for batch treasury workloads."""

from __future__ import annotations

import logging
import os
from collections import deque
from collections.abc import Iterable, Iterator
from concurrent.futures import (
    Future,
    ProcessPoolExecutor,
)
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileResult:
    """Result of parsing a single file."""

    path: str
    status: str
    transactions: pd.DataFrame = field(default_factory=pd.DataFrame)
    error: str = ""


def _parse_single_file(
    file_path: str,
    format_name: str | None,
) -> FileResult:
    """Parse one file in a worker process."""
    from .additional_parsers import (
        create_parser,
        detect_statement_format,
    )

    try:
        fmt = format_name or detect_statement_format(file_path)
        parser = create_parser(file_path, fmt)
        df = parser.parse()
        return FileResult(
            path=file_path,
            status="SUCCESS",
            transactions=df,
        )
    except Exception as exc:
        return FileResult(
            path=file_path,
            status="FAILED",
            error=f"{type(exc).__name__}: {exc}",
        )


def iter_files_parallel(
    file_paths: Iterable[str | Path],
    *,
    format_name: str | None = None,
    max_workers: int | None = None,
    max_pending: int | None = None,
) -> Iterator[FileResult]:
    """Yield ordered results with a bounded window of submitted files.

    At most ``max_pending`` futures and their results are retained (default:
    twice the worker count). Input paths are consumed incrementally. Each
    worker still materializes one file's DataFrame; this is a file-count bound,
    not a byte or execution-time limit. Closing the iterator cancels queued
    work and waits for already running workers to finish.
    """
    workers = max_workers if max_workers is not None else (os.cpu_count() or 1)
    pending_limit = max_pending if max_pending is not None else workers * 2
    if workers <= 0 or pending_limit <= 0:
        raise ValueError("Worker and pending-file limits must be positive")
    paths = iter(file_paths)
    pending: deque[tuple[str, Future[FileResult]]] = deque()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        try:
            for path in islice(paths, pending_limit):
                name = str(path)
                pending.append(
                    (
                        name,
                        executor.submit(_parse_single_file, name, format_name),
                    )
                )
            while pending:
                name, future = pending.popleft()
                try:
                    result = future.result()
                except Exception as exc:
                    result = FileResult(
                        path=name,
                        status="FAILED",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                yield result
                for path in islice(paths, 1):
                    name = str(path)
                    pending.append(
                        (
                            name,
                            executor.submit(
                                _parse_single_file, name, format_name
                            ),
                        )
                    )
        finally:
            for _, future in pending:
                future.cancel()


def parse_files_parallel(
    file_paths: list[str | Path],
    *,
    format_name: str | None = None,
    max_workers: int | None = None,
    max_pending: int | None = None,
) -> list[FileResult]:
    """Parse files in order with bounded scheduling and a materialized result.

    Uses process-based parallelism to bypass the GIL. ``max_workers`` defaults
    to the CPU count; ``max_pending`` defaults to twice that count. Prefer
    :func:`iter_files_parallel` when results themselves must not accumulate.
    A single file avoids process overhead. Neither API imposes a deadline.
    """
    if max_workers is not None and max_workers <= 0:
        raise ValueError("Worker and pending-file limits must be positive")
    if max_pending is not None and max_pending <= 0:
        raise ValueError("Worker and pending-file limits must be positive")
    if not file_paths:
        return []
    # Single file - skip process overhead.
    if len(file_paths) == 1:
        return [_parse_single_file(str(file_paths[0]), format_name)]
    return list(
        iter_files_parallel(
            file_paths,
            format_name=format_name,
            max_workers=max_workers,
            max_pending=max_pending,
        )
    )
