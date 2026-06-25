"""
Generate two synthetic UK-bank statement PDFs for the hybrid examples.

Why synthetic? Real bank PDFs cannot be redistributed (PII + copyright).
This script produces two reproducible files that exercise both code
paths the v0.0.5 hybrid pipeline cares about:

  sample_data/digital.pdf    Text-layer PDF (Path B: text-LLM)
  sample_data/scanned.pdf    Image-only PDF (Path C: vision-LLM)

The "scanned" PDF is created by rendering the digital one to a
bitmap and re-wrapping it as a PDF page — the same shape as a
photocopied or faxed statement, with no extractable text layer.

Run once before any of the 0X_*.py examples:

    cd examples/hybrid
    pip install reportlab pypdfium2 pillow
    python generate_sample_pdfs.py

Cross-platform: pure Python, no system dependencies.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

EXAMPLE_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = EXAMPLE_ROOT / "sample_data"
DIGITAL_PDF = OUTPUT_DIR / "digital.pdf"
SCANNED_PDF = OUTPUT_DIR / "scanned.pdf"

# Statement metadata. Tweak freely — every example reads it from here
# so the Golden Rule arithmetic stays internally consistent.
ACCOUNT_NUMBER = "12345678"
SORT_CODE = "12-34-56"
CURRENCY = "GBP"
OPENING_BALANCE = Decimal("1500.00")
STATEMENT_PERIOD = "2026-04-01 to 2026-04-08"

# (date, description, amount). Negative = debit, positive = credit.
TRANSACTIONS: list[tuple[str, str, Decimal]] = [
    ("2026-04-01", "SALARY ACME CORP", Decimal("2500.00")),
    ("2026-04-01", "STANDING ORDER RENT", Decimal("-1200.00")),
    ("2026-04-02", "CARD PAYMENT 12:49 COFFEE SHOP", Decimal("-3.85")),
    ("2026-04-02", "AMZN MKTPLACE 2026-04-02 #A1B2C3", Decimal("-29.99")),
    ("2026-04-03", "CONTACTLESS TFL TRAVEL", Decimal("-7.40")),
    ("2026-04-03", "REFUND ZARA RETURNS", Decimal("39.95")),
    ("2026-04-04", "DIRECT DEBIT BRITISH GAS", Decimal("-89.50")),
    ("2026-04-05", "AMZN MKTPLACE 2026-04-05 #Z9Y8X7", Decimal("-29.99")),
    ("2026-04-06", "CARD PAYMENT 19:02 SAINSBURYS", Decimal("-54.20")),
    ("2026-04-07", "INTEREST PAID", Decimal("0.42")),
    ("2026-04-08", "CARD PAYMENT 08:15 COFFEE SHOP", Decimal("-3.85")),
]


def closing_balance() -> Decimal:
    """Return the closing balance derived from the sample transactions."""
    return OPENING_BALANCE + sum(
        (amount for _date, _desc, amount in TRANSACTIONS),
        Decimal("0"),
    )


def _try_import_reportlab() -> object:
    """Import reportlab helpers or exit with an install hint."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        return canvas, A4, mm
    except ImportError as exc:
        raise SystemExit(
            "reportlab is required to generate the sample PDFs.\n"
            "Install it with: pip install reportlab"
        ) from exc


def _try_import_pypdfium2() -> object:
    """Import pypdfium2 or exit with an install hint."""
    try:
        import pypdfium2 as pdfium

        return pdfium
    except ImportError as exc:
        raise SystemExit(
            "pypdfium2 is required to rasterise the scanned PDF.\n"
            "Install it with: pip install pypdfium2"
        ) from exc


def _try_import_pil() -> object:
    """Import Pillow's Image or exit with an install hint."""
    try:
        from PIL import Image

        return Image
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required to wrap the rasterised pages.\n"
            "Install it with: pip install pillow"
        ) from exc


def render_digital_pdf(target: Path) -> None:
    """Write a text-layer PDF that pypdf can extract cleanly."""
    canvas_mod, A4, mm = _try_import_reportlab()  # type: ignore[misc]
    _page_w, page_h = A4

    target.parent.mkdir(parents=True, exist_ok=True)
    c = canvas_mod.Canvas(str(target), pagesize=A4)

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, page_h - 25 * mm, "EXAMPLE BANK PLC")
    c.setFont("Helvetica", 10)
    c.drawString(
        20 * mm,
        page_h - 32 * mm,
        "Synthetic statement for hybrid pipeline examples",
    )

    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, page_h - 45 * mm, f"Account: {ACCOUNT_NUMBER}")
    c.drawString(80 * mm, page_h - 45 * mm, f"Sort code: {SORT_CODE}")
    c.drawString(20 * mm, page_h - 51 * mm, f"Currency: {CURRENCY}")
    c.drawString(80 * mm, page_h - 51 * mm, f"Period:   {STATEMENT_PERIOD}")
    c.drawString(
        20 * mm,
        page_h - 57 * mm,
        f"Opening balance: {OPENING_BALANCE:.2f}",
    )
    c.drawString(
        20 * mm,
        page_h - 63 * mm,
        f"Closing balance: {closing_balance():.2f}",
    )

    # Header row.
    y = page_h - 78 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Date")
    c.drawString(45 * mm, y, "Description")
    c.drawString(150 * mm, y, "Amount")
    c.line(20 * mm, y - 2, 190 * mm, y - 2)

    # Rows.
    c.setFont("Helvetica", 9)
    y -= 8 * mm
    for date, description, amount in TRANSACTIONS:
        c.drawString(20 * mm, y, date)
        c.drawString(45 * mm, y, description)
        c.drawRightString(180 * mm, y, f"{amount:.2f}")
        y -= 6 * mm

    c.showPage()
    c.save()


def render_scanned_pdf(source: Path, target: Path) -> None:
    """Re-render `source` to a bitmap and wrap it as an image-only PDF.

    The resulting PDF mimics a photocopy or fax: pixels only, no
    extractable text. This forces the orchestrator's
    LOW_TEXT_DENSITY_THRESHOLD heuristic to route via the vision
    path (Path C).
    """
    pdfium = _try_import_pypdfium2()  # type: ignore[misc]
    _try_import_pil()  # ensure Pillow is installed before rendering

    pdf = pdfium.PdfDocument(str(source))
    pages = []
    for index in range(len(pdf)):
        page = pdf[index]
        bitmap = page.render(scale=2.0)
        pages.append(bitmap.to_pil().convert("RGB"))

    if not pages:
        raise RuntimeError(f"No pages rendered from {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(
        target,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=144.0,
    )


def main() -> None:
    """Generate the digital and scanned sample PDFs."""
    print(f"Output directory: {OUTPUT_DIR}")
    print()
    print("=" * 60)
    print("Generating digital PDF (text layer present)...")
    print("=" * 60)
    render_digital_pdf(DIGITAL_PDF)
    size_kb = DIGITAL_PDF.stat().st_size / 1024
    print(f"  -> {DIGITAL_PDF.relative_to(EXAMPLE_ROOT)} ({size_kb:.1f} KB)")
    print()

    print("=" * 60)
    print("Generating scanned PDF (image-only, simulates photocopy)...")
    print("=" * 60)
    render_scanned_pdf(DIGITAL_PDF, SCANNED_PDF)
    size_kb = SCANNED_PDF.stat().st_size / 1024
    print(f"  -> {SCANNED_PDF.relative_to(EXAMPLE_ROOT)} ({size_kb:.1f} KB)")
    print()

    print("Statement summary:")
    print(f"  Account:         {ACCOUNT_NUMBER}")
    print(f"  Period:          {STATEMENT_PERIOD}")
    print(f"  Opening balance: {OPENING_BALANCE:.2f} {CURRENCY}")
    print(f"  Closing balance: {closing_balance():.2f} {CURRENCY}")
    print(f"  Transactions:    {len(TRANSACTIONS)}")
    print()
    print("Next: try `python 01_smart_ingest_deterministic.py`")


if __name__ == "__main__":
    sys.exit(main())
