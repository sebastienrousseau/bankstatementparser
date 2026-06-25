# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for the bulk directory scanner (#v0.0.8)."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from bankstatementparser.hybrid import scanner
from bankstatementparser.hybrid.orchestrator import IngestResult
from bankstatementparser.hybrid.scanner import scan_and_ingest
from bankstatementparser.hybrid.verification import (
    BalanceVerification,
    VerificationStatus,
)

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


def _ingest_result_with_balances(
    opening: Decimal, closing: Decimal
) -> IngestResult:
    return IngestResult(
        source_method="deterministic",
        source_format="camt",
        transactions=(),
        verification=BalanceVerification(
            status=VerificationStatus.VERIFIED,
            opening_balance=opening,
            closing_balance=closing,
            total_credits=Decimal("0"),
            total_debits=Decimal("0"),
            expected_delta=Decimal("0"),
            actual_delta=Decimal("0"),
            discrepancy=Decimal("0"),
            message="ok",
        ),
    )


def test_scan_continuity_verified_across_chained_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "01-jan.xml").write_text("jan")
    (tmp_path / "02-feb.xml").write_text("feb")
    balances = {
        "01-jan.xml": (Decimal("100"), Decimal("250")),
        "02-feb.xml": (Decimal("250"), Decimal("300")),
    }

    def fake_ingest(path: Path) -> IngestResult:
        return _ingest_result_with_balances(*balances[Path(path).name])

    monkeypatch.setattr(scanner, "smart_ingest", fake_ingest)
    result = scan_and_ingest(tmp_path)
    assert result.continuity is not None
    assert result.continuity.status is VerificationStatus.VERIFIED
    assert result.continuity.checked_links == 1


def test_scan_continuity_flags_gap_between_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "01-jan.xml").write_text("jan")
    (tmp_path / "02-feb.xml").write_text("feb")
    balances = {
        "01-jan.xml": (Decimal("100"), Decimal("250")),
        "02-feb.xml": (Decimal("400"), Decimal("500")),
    }

    def fake_ingest(path: Path) -> IngestResult:
        return _ingest_result_with_balances(*balances[Path(path).name])

    monkeypatch.setattr(scanner, "smart_ingest", fake_ingest)
    result = scan_and_ingest(tmp_path)
    assert result.continuity is not None
    assert result.continuity.status is VerificationStatus.DISCREPANCY
    brk = result.continuity.breaks[0]
    assert brk.previous_label.endswith("01-jan.xml")
    assert brk.next_label.endswith("02-feb.xml")
    assert brk.gap == Decimal("150")


def test_scan_continuity_none_for_single_file(tmp_path: Path) -> None:
    shutil.copy(CAMT_FIXTURE, tmp_path / "statement.xml")
    result = scan_and_ingest(tmp_path)
    assert result.continuity is None


def test_scan_continuity_unverifiable_without_balances(
    tmp_path: Path,
) -> None:
    # Real fixtures ingested without balances: links exist but none
    # can be checked, so the chain reports UNVERIFIABLE (cannot
    # verify).
    shutil.copy(CAMT_FIXTURE, tmp_path / "a.xml")
    shutil.copy(CAMT_FIXTURE, tmp_path / "b.xml")
    result = scan_and_ingest(tmp_path)
    assert result.continuity is not None
    assert result.continuity.status is VerificationStatus.UNVERIFIABLE
    assert result.continuity.unchecked_links == 1
