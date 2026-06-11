# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for the bulk directory scanner (#v0.0.8)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bankstatementparser.hybrid.scanner import scan_and_ingest

CAMT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "test_data"
    / "camt.053.001.02.xml"
)


def test_scan_single_xml_file(tmp_path: Path) -> None:
    shutil.copy(CAMT_FIXTURE, tmp_path / "statement.xml")
    result = scan_and_ingest(tmp_path)
    assert result.file_count == 1
    assert result.total_unique >= 1
    assert result.total_skipped == 0
    assert len(result.results) == 1
    assert result.results[0].source_method == "deterministic"


def test_scan_deduplicates_across_files(tmp_path: Path) -> None:
    shutil.copy(CAMT_FIXTURE, tmp_path / "a.xml")
    shutil.copy(CAMT_FIXTURE, tmp_path / "b.xml")
    result = scan_and_ingest(tmp_path)
    assert result.file_count == 2
    # Same file twice = all dupes from the second file
    assert result.total_skipped > 0
    assert result.total_unique == len(result.results[0].transactions)


def test_scan_respects_extension_filter(tmp_path: Path) -> None:
    shutil.copy(CAMT_FIXTURE, tmp_path / "statement.xml")
    (tmp_path / "notes.txt").write_text("ignore me")
    result = scan_and_ingest(tmp_path)
    assert result.file_count == 1  # .txt filtered out


def test_scan_custom_pattern(tmp_path: Path) -> None:
    sub = tmp_path / "2026" / "04"
    sub.mkdir(parents=True)
    shutil.copy(CAMT_FIXTURE, sub / "statement.xml")
    result = scan_and_ingest(tmp_path, pattern="2026/**/*.xml")
    assert result.file_count == 1


def test_scan_preserves_seen_hashes_across_calls(
    tmp_path: Path,
) -> None:
    shutil.copy(CAMT_FIXTURE, tmp_path / "statement.xml")
    seen: set[str] = set()
    r1 = scan_and_ingest(tmp_path, seen_hashes=seen)
    assert r1.total_unique > 0
    assert len(seen) > 0
    # Second scan with same seen_hashes = all skipped
    r2 = scan_and_ingest(tmp_path, seen_hashes=seen)
    assert r2.total_unique == 0
    assert r2.total_skipped > 0


def test_scan_not_a_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Not a directory"):
        scan_and_ingest(tmp_path / "nonexistent")


def test_scan_empty_directory(tmp_path: Path) -> None:
    result = scan_and_ingest(tmp_path)
    assert result.file_count == 0
    assert result.total_unique == 0


def test_scan_custom_extensions(tmp_path: Path) -> None:
    shutil.copy(CAMT_FIXTURE, tmp_path / "statement.xml")
    (tmp_path / "statement.csv").write_text("a,b\n1,2")
    result = scan_and_ingest(tmp_path, extensions={".xml"})
    assert result.file_count == 1  # .csv filtered out


def test_scan_skips_failed_files(tmp_path: Path) -> None:
    shutil.copy(CAMT_FIXTURE, tmp_path / "good.xml")
    (tmp_path / "bad.xml").write_text("not valid xml")
    result = scan_and_ingest(tmp_path)
    # good.xml succeeds, bad.xml logged as warning
    assert result.file_count == 2
    assert len(result.results) >= 1


def test_scan_records_failures_with_count(tmp_path: Path) -> None:
    (tmp_path / "bad.xml").write_text("not valid xml")
    result = scan_and_ingest(tmp_path)
    assert result.failure_count == 1
    assert result.failures[0].path.endswith("bad.xml")
    assert result.failures[0].error
