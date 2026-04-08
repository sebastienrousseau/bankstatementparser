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
from concurrent.futures import (
    ProcessPoolExecutor,
    as_completed,
)
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileResult:
    """Result of parsing a single file."""

    path: str
    status: str
    transactions: pd.DataFrame = field(
        default_factory=pd.DataFrame
    )
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
            error=str(exc),
        )


def parse_files_parallel(
    file_paths: list[str | Path],
    *,
    format_name: str | None = None,
    max_workers: int | None = None,
) -> list[FileResult]:
    """Parse multiple statement files in parallel.

    Uses process-based parallelism to bypass the GIL and
    maximise throughput on multi-core systems. Each file is
    parsed in its own worker process.

    Args:
        file_paths: Paths to statement files.
        format_name: Force a specific format for all files.
            When *None*, each file is auto-detected.
        max_workers: Maximum worker processes. Defaults to
            the number of CPU cores.

    Returns:
        List of ``FileResult`` in the same order as *file_paths*.
    """
    if not file_paths:
        return []

    str_paths = [str(p) for p in file_paths]

    # Single file — skip process overhead
    if len(str_paths) == 1:
        return [_parse_single_file(str_paths[0], format_name)]

    results: dict[str, FileResult] = {}

    with ProcessPoolExecutor(
        max_workers=max_workers
    ) as executor:
        future_to_path = {
            executor.submit(
                _parse_single_file, p, format_name
            ): p
            for p in str_paths
        }
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                results[path] = future.result()
            except Exception as exc:  # pragma: no cover
                results[path] = FileResult(
                    path=path,
                    status="FAILED",
                    error=str(exc),
                )

    # Preserve original order
    return [results[p] for p in str_paths]
