# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for PDF Document Forensics and Anti-Tampering Integrity Inspector."""

from pathlib import Path

import pytest

from bankstatementparser.forensics import (
    ForensicsReport,
    ForensicVerdict,
    inspect_pdf_forensics,
)


def test_inspect_pdf_forensics_nonexistent_file() -> None:
    """Nonexistent file returns high risk tamper report with clear error finding."""
    report = inspect_pdf_forensics("/nonexistent/fake/file.pdf")
    assert isinstance(report, ForensicsReport)
    assert report.verdict == ForensicVerdict.HIGH_RISK_TAMPERED
    assert report.is_tampered is True
    assert report.risk_score == 1.00
    assert len(report.findings) == 1
    assert report.findings[0].category == "FILE_IO"


def test_inspect_pdf_forensics_clean_synthetic_pdf(tmp_path: Path) -> None:
    """Standard benign PDF produces low or genuine risk report."""
    fake_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Producer (SAP ERP Financial Engine) /CreationDate (D:20260101120000) /ModDate (D:20260101120000) >>\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n"
        b"trailer\n<< /Size 5 /Root 1 0 R /Info 4 0 R >>\n"
        b"startxref\n200\n%%EOF\n"
    )
    p = tmp_path / "clean_statement.pdf"
    p.write_bytes(fake_pdf)

    report = inspect_pdf_forensics(p)
    assert report.verdict == ForensicVerdict.GENUINE
    assert report.is_tampered is False
    assert report.risk_score == 0.00
    assert report.producer == "SAP ERP Financial Engine"


def test_inspect_pdf_forensics_tampered_photoshop_signatures(
    tmp_path: Path,
) -> None:
    """Detects Photoshop/Canva editor signatures and revision trailers."""
    tampered_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Producer (Adobe Photoshop 2026) /Creator (Canva Web Exporter) /CreationDate (D:20260101) /ModDate (D:20260315) >>\nendobj\n"
        b"startxref\n100\n%%EOF\n"
        b"2 0 obj\n<< /Type /Update >>\nendobj\n"
        b"startxref\n250\n%%EOF\n"
        b"3 0 obj\n<< /Type /Update2 >>\nendobj\n"
        b"startxref\n400\n%%EOF\n"
        b"4 0 obj\n<< /Type /Update3 >>\nendobj\n"
        b"startxref\n550\n%%EOF\n"
    )
    p = tmp_path / "tampered_statement.pdf"
    p.write_bytes(tampered_pdf)

    report = inspect_pdf_forensics(p)
    assert report.verdict in (
        ForensicVerdict.SUSPICIOUS,
        ForensicVerdict.HIGH_RISK_TAMPERED,
    )
    assert report.risk_score >= 0.45
    assert any(f.category == "SOFTWARE_PROVENANCE" for f in report.findings)
    assert any(f.category == "REVISION_TREE" for f in report.findings)

    d = report.to_dict()
    assert d["verdict"] in ("SUSPICIOUS", "HIGH_RISK_TAMPERED")
    assert len(d["findings"]) >= 2


def test_inspect_pdf_forensics_date_drift_and_fonts() -> None:
    """Tests date drift and high font count typography anomaly."""
    fonts_str = b"".join(
        f"/BaseFont /FontSubset{i}\n".encode() for i in range(15)
    )
    drift_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Producer (BankCoreEngine) /CreationDate (D:20260101) /ModDate (D:20260215) >>\nendobj\n"
        + fonts_str
        + b"startxref\n100\n%%EOF\n"
    )
    report = inspect_pdf_forensics(drift_pdf)
    assert report.verdict == ForensicVerdict.SUSPICIOUS
    assert any(f.category == "METADATA_DRIFT" for f in report.findings)
    assert any(f.category == "TYPOGRAPHY_ANOMALY" for f in report.findings)

    # Test single low risk finding
    low_risk_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Producer (BankCoreEngine) /CreationDate (D:20260101) /ModDate (D:20260215) >>\nendobj\n"
        b"startxref\n100\n%%EOF\n"
    )
    rep_low = inspect_pdf_forensics(low_risk_pdf)
    assert rep_low.verdict == ForensicVerdict.LOW_RISK
    assert rep_low.is_tampered is False


def test_extract_pdf_metadata_direct_fallback() -> None:
    """Tests _extract_pdf_metadata manual regex fallback path directly."""
    from bankstatementparser.forensics import _extract_pdf_metadata

    raw_pdf = (
        b"/Producer (CustomProd) /Creator (CustomCreat) "
        b"/CreationDate (D:20260101) /ModDate (D:20260102) %%EOF"
    )
    meta = _extract_pdf_metadata(raw_pdf)
    assert meta["producer"] == "CustomProd"
    assert meta["creator"] == "CustomCreat"
    assert meta["creation_date"] == "D:20260101"
    assert meta["mod_date"] == "D:20260102"
    assert meta["revisions"] == 1

    empty_meta = _extract_pdf_metadata(b"Plain text no metadata")
    assert empty_meta["producer"] is None
    assert empty_meta["creator"] is None
    assert empty_meta["creation_date"] is None
    assert empty_meta["mod_date"] is None


def test_extract_pdf_metadata_pypdf_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests _extract_pdf_metadata when pypdf reader extracts metadata dictionary."""
    import sys
    from types import ModuleType
    from typing import Any

    from bankstatementparser.forensics import _extract_pdf_metadata

    class FakePdfReader:
        def __init__(self, stream: Any) -> None:
            self.metadata = {
                "/Producer": "GenuineProducer",
                "/Creator": "GenuineCreator",
                "/CreationDate": "D:20260101",
                "/ModDate": "D:20260101",
            }

    fake_pypdf = ModuleType("pypdf")
    fake_pypdf.PdfReader = FakePdfReader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    meta = _extract_pdf_metadata(b"%PDF-1.4 %%EOF")
    assert meta["producer"] == "GenuineProducer"
    assert meta["creator"] == "GenuineCreator"
    assert meta["creation_date"] == "D:20260101"
