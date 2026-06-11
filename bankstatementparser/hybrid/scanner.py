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

"""Bulk directory scanner for the hybrid pipeline.

Scans an organized folder tree, runs :func:`smart_ingest` on every
matching file, and deduplicates file-by-file via
:meth:`Deduplicator.dedupe_by_hash` (each file is one batch, so
repeats within a statement survive while overlapping exports are
skipped). Designed for the common treasury pattern of
``statements/2026/04/*.pdf``.

Usage::

    from bankstatementparser.hybrid.scanner import scan_and_ingest

    batch = scan_and_ingest("statements/", pattern="**/*.pdf")
    print(f"{len(batch.results)} files, {batch.total_unique} unique tx")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from ..transaction_deduplicator import Deduplicator
from ..transaction_models import Transaction
from .orchestrator import IngestResult, smart_ingest

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


@dataclass(frozen=True)
class FileFailure:
    """A file that could not be ingested during a scan."""

    path: str
    error: str


@dataclass(frozen=True)
class ScanResult:
    """Output of :func:`scan_and_ingest`."""

    results: tuple[IngestResult, ...]
    unique_transactions: tuple[Transaction, ...]
    skipped_hashes: tuple[str, ...]
    file_count: int
    total_unique: int
    total_skipped: int
    failures: tuple[FileFailure, ...] = ()

    @property
    def failure_count(self) -> int:
        """Number of files that failed to ingest."""
        return len(self.failures)


def scan_and_ingest(
    directory: PathLike,
    *,
    pattern: str = "**/*",
    seen_hashes: Optional[set[str]] = None,
    extensions: Optional[set[str]] = None,
) -> ScanResult:
    """Scan a directory and run :func:`smart_ingest` on every match.

    Args:
        directory: Root directory to scan.
        pattern: Glob pattern relative to ``directory``. Defaults
            to ``**/*`` (recursive, all files).
        seen_hashes: Optional set of already-ingested hashes for
            cross-batch dedup. Mutated in-place so callers can
            persist state.
        extensions: Allowed file extensions (lowercase, with dot).
            Defaults to ``{".xml", ".csv", ".ofx", ".qfx",
            ".mt940", ".sta", ".pdf"}``.

    Returns:
        A :class:`ScanResult` with all per-file results, the
        deduplicated transaction list, and the skipped-hash list.
    """
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")

    if extensions is None:
        extensions = {
            ".xml",
            ".csv",
            ".ofx",
            ".qfx",
            ".mt940",
            ".sta",
            ".pdf",
        }
    if seen_hashes is None:
        seen_hashes = set()

    files = sorted(
        p
        for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in extensions
    )

    dedup = Deduplicator()
    all_results: list[IngestResult] = []
    unique: list[Transaction] = []
    skipped: list[str] = []
    failures: list[FileFailure] = []

    for file_path in files:
        logger.info("Ingesting %s", file_path)
        try:
            result = smart_ingest(file_path)
        except Exception as exc:
            logger.warning("Failed to ingest %s: %s", file_path, exc)
            failures.append(FileFailure(path=str(file_path), error=str(exc)))
            continue
        all_results.append(result)
        # Each file is its own dedup batch: genuine repeats within
        # one statement survive, while a file that re-exports
        # already-seen transactions is skipped.
        file_unique, file_skipped = dedup.dedupe_by_hash(
            result.transactions, seen_hashes=seen_hashes
        )
        unique.extend(file_unique)
        skipped.extend(file_skipped)

    if failures:
        logger.warning(
            "Scan finished with %d of %d files failed",
            len(failures),
            len(files),
        )

    return ScanResult(
        results=tuple(all_results),
        unique_transactions=tuple(unique),
        skipped_hashes=tuple(skipped),
        file_count=len(files),
        total_unique=len(unique),
        total_skipped=len(skipped),
        failures=tuple(failures),
    )
