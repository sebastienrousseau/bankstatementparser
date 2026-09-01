# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""PDF Document Forensics and Anti-Tampering Integrity Inspector.

Inspects PDF byte structures, font dictionaries, and metadata timestamps
to detect document modifications, Photoshop/Canva tampering, suspicious
producer tools, and revision tree inconsistencies on financial statements.
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ForensicVerdict(str, Enum):
    """Forensic integrity risk assessment verdict."""

    GENUINE = "GENUINE"
    LOW_RISK = "LOW_RISK"
    SUSPICIOUS = "SUSPICIOUS"
    HIGH_RISK_TAMPERED = "HIGH_RISK_TAMPERED"


@dataclass(frozen=True)
class ForensicFinding:
    """An individual forensic observation or anomaly finding."""

    category: str
    severity: str
    description: str
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert finding to dictionary."""
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}


@dataclass(frozen=True)
class ForensicsReport:
    """Comprehensive forensic analysis report for a statement file."""

    verdict: ForensicVerdict
    risk_score: float
    is_tampered: bool
    creation_date: str | None
    modification_date: str | None
    producer: str | None
    creator: str | None
    revision_count: int
    findings: list[ForensicFinding]

    def to_dict(self) -> dict[str, Any]:
        """Convert report to clean serializable dictionary."""
        return {
            "verdict": self.verdict.value,
            "risk_score": self.risk_score,
            "is_tampered": self.is_tampered,
            "creation_date": self.creation_date,
            "modification_date": self.modification_date,
            "producer": self.producer,
            "creator": self.creator,
            "revision_count": self.revision_count,
            "findings": [f.to_dict() for f in self.findings],
        }


# Tools known for manual image/document manipulation (not standard banking core systems)
_SUSPICIOUS_SOFTWARE_KEYWORDS = (
    "photoshop",
    "canva",
    "gimp",
    "ilovepdf",
    "sejda",
    "pdfescape",
    "smallpdf",
    "sodapdf",
    "inkscape",
    "illustrator",
    "coreldraw",
    "acrobat pro patch",
    "pdf editor",
    "foxit phantom",
    "master pdf",
)

# Standard banking core / treasury report engines
_BENIGN_PRODUCERS = (
    "sap",
    "oracle",
    "citi",
    "jpmorgan",
    "fiserv",
    "temenos",
    "fisp",
    "openbill",
    "jasperreports",
    "apache fop",
    "itext",
    "reportlab",
    "cairo",
    "pdfkit",
    "wkhtmltopdf",
    "weasyprint",
    "quartz",
)


def _extract_pdf_metadata(pdf_bytes: bytes) -> dict[str, Any]:
    """Extract metadata, revisions, and font signatures from PDF bytes."""
    meta: dict[str, Any] = {
        "producer": None,
        "creator": None,
        "creation_date": None,
        "mod_date": None,
        "revisions": pdf_bytes.count(b"%%EOF"),
        "fonts": set(),
        "has_images": b"/Image" in pdf_bytes or b"/XObject" in pdf_bytes,
    }

    # Attempt to extract metadata via pypdf if available
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        doc_info = reader.metadata
        if doc_info:
            meta["producer"] = str(doc_info.get("/Producer", "") or "") or None
            meta["creator"] = str(doc_info.get("/Creator", "") or "") or None
            meta["creation_date"] = (
                str(doc_info.get("/CreationDate", "") or "") or None
            )
            meta["mod_date"] = str(doc_info.get("/ModDate", "") or "") or None
    except Exception:  # noqa: S110 # nosec B110
        pass

    # Fallback / augment with raw byte regex scanning
    if not meta["producer"]:
        prod_m = re.search(rb"/Producer\s*\(([^)]+)\)", pdf_bytes)
        if prod_m:
            meta["producer"] = prod_m.group(1).decode(
                "latin-1", errors="ignore"
            )

    if not meta["creator"]:
        creat_m = re.search(rb"/Creator\s*\(([^)]+)\)", pdf_bytes)
        if creat_m:
            meta["creator"] = creat_m.group(1).decode(
                "latin-1", errors="ignore"
            )

    if not meta["creation_date"]:
        cdate_m = re.search(rb"/CreationDate\s*\(([^)]+)\)", pdf_bytes)
        if cdate_m:
            meta["creation_date"] = cdate_m.group(1).decode(
                "latin-1", errors="ignore"
            )

    if not meta["mod_date"]:
        mdate_m = re.search(rb"/ModDate\s*\(([^)]+)\)", pdf_bytes)
        if mdate_m:
            meta["mod_date"] = mdate_m.group(1).decode(
                "latin-1", errors="ignore"
            )

    # Extract font signatures
    font_matches = re.findall(rb"/BaseFont\s*/([A-Za-z0-9\+\-_]+)", pdf_bytes)
    meta["fonts"] = {
        f.decode("latin-1", errors="ignore") for f in font_matches
    }

    return meta


def inspect_pdf_forensics(
    pdf_input: str | Path | bytes,
) -> ForensicsReport:
    """Inspect a PDF bank statement for signs of alteration, forgery, or tampering.

    Evaluates:
    - Incremental revision trees (multiple `%%EOF` update trailers).
    - Image editing tool signatures in Producer/Creator metadata.
    - Timestamp drift between CreationDate and ModDate.
    - Fragmented font subsets and mixed typography.

    Args:
        pdf_input: File path (str or Path) or raw PDF bytes.

    Returns:
        Structured ForensicsReport with risk score and verdict.
    """
    if isinstance(pdf_input, (str, Path)):
        p = Path(pdf_input)
        if not p.exists():
            return ForensicsReport(
                verdict=ForensicVerdict.HIGH_RISK_TAMPERED,
                risk_score=1.00,
                is_tampered=True,
                creation_date=None,
                modification_date=None,
                producer=None,
                creator=None,
                revision_count=0,
                findings=[
                    ForensicFinding(
                        category="FILE_IO",
                        severity="CRITICAL",
                        description=f"PDF statement file not found: {p}",
                    )
                ],
            )
        pdf_bytes = p.read_bytes()
    else:
        pdf_bytes = pdf_input

    meta = _extract_pdf_metadata(pdf_bytes)
    findings: list[ForensicFinding] = []
    risk_points = 0.0

    producer = meta.get("producer") or ""
    creator = meta.get("creator") or ""
    cdate = meta.get("creation_date") or ""
    mdate = meta.get("mod_date") or ""
    revisions = meta.get("revisions", 1)
    fonts = meta.get("fonts", set())

    # 1. Check for suspicious image manipulation software
    combined_software = f"{producer} {creator}".lower()
    for sw in _SUSPICIOUS_SOFTWARE_KEYWORDS:
        if sw in combined_software:
            risk_points += 0.45
            findings.append(
                ForensicFinding(
                    category="SOFTWARE_PROVENANCE",
                    severity="HIGH",
                    description=f"Statement was produced or modified using image editing software '{sw}'.",
                    evidence=f"Producer: '{producer}', Creator: '{creator}'",
                )
            )
            break

    # 2. Check for incremental revision updates (indicative of layered redaction or inserted text)
    if revisions > 2:
        risk_points += 0.30
        findings.append(
            ForensicFinding(
                category="REVISION_TREE",
                severity="MEDIUM",
                description=f"PDF contains {revisions} incremental revision trailers (%%EOF markers).",
                evidence=f"Found {revisions} trailers",
            )
        )

    # 3. Check for Date Drift (ModDate exists and differs from CreationDate)
    if cdate and mdate and cdate != mdate:
        # Non-identical creation and modification date
        risk_points += 0.15
        findings.append(
            ForensicFinding(
                category="METADATA_DRIFT",
                severity="LOW",
                description="PDF modification timestamp differs from creation timestamp.",
                evidence=f"Creation: '{cdate}', Modified: '{mdate}'",
            )
        )

    # 4. Check for Fragmented Font Subsets
    # A standard generated statement typically uses 1 to 6 consistent fonts.
    if len(fonts) > 12:
        risk_points += 0.20
        findings.append(
            ForensicFinding(
                category="TYPOGRAPHY_ANOMALY",
                severity="MEDIUM",
                description=f"PDF contains unusually high number of distinct embedded font subsets ({len(fonts)} fonts).",
                evidence=f"Fonts: {', '.join(sorted(fonts)[:8])}...",
            )
        )

    # Determine final risk score and verdict
    final_risk = min(1.00, round(risk_points, 2))

    if final_risk >= 0.60:
        verdict = ForensicVerdict.HIGH_RISK_TAMPERED
        is_tampered = True
    elif final_risk >= 0.35:
        verdict = ForensicVerdict.SUSPICIOUS
        is_tampered = False
    elif final_risk > 0.00:
        verdict = ForensicVerdict.LOW_RISK
        is_tampered = False
    else:
        verdict = ForensicVerdict.GENUINE
        is_tampered = False

    return ForensicsReport(
        verdict=verdict,
        risk_score=final_risk,
        is_tampered=is_tampered,
        creation_date=cdate or None,
        modification_date=mdate or None,
        producer=producer or None,
        creator=creator or None,
        revision_count=revisions,
        findings=findings,
    )
