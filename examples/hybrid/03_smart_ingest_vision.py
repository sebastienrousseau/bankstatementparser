"""
Example 03 — Path C: vision-LLM extraction for scanned PDFs.

When `pypdf` cannot extract enough text from a PDF (i.e. the file is
a scan, photocopy, or fax), `smart_ingest()` automatically falls
through to the multimodal vision path. This example walks through
that automatic handover end-to-end.

Modes:

  LIVE   Set BSP_HYBRID_VISION_MODEL to a real multimodal model.
         Examples:
           BSP_HYBRID_VISION_MODEL=ollama/llava   (local, free)
           BSP_HYBRID_VISION_MODEL=gpt-4o         (OpenAI, paid)

  MOCK   No env var set — uses an injected completion stub so the
         example always runs end-to-end. CI-safe.

Prerequisites:
    pip install 'bankstatementparser[hybrid-vision]'
    python examples/hybrid/generate_sample_pdfs.py

Run:
    python examples/hybrid/03_smart_ingest_vision.py

Cross-platform: identical on macOS / Linux / WSL. pypdfium2 is a
pure-Python wheel so there is no `poppler` install step.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser.hybrid import (  # noqa: E402
    LOW_TEXT_DENSITY_THRESHOLD,
    VisionExtractor,
    pdf_text,  # noqa: E402
    smart_ingest,
)

EXAMPLE_DIR = Path(__file__).resolve().parent
SAMPLE_PDF = EXAMPLE_DIR / "sample_data" / "scanned.pdf"


# ---------------------------------------------------------------------------
# Mock multimodal completion — used when BSP_HYBRID_VISION_MODEL is unset
# ---------------------------------------------------------------------------


def _mock_vision_completion(**kwargs: Any) -> dict[str, Any]:
    """Return a fixed JSON payload as if a multimodal model had read the scan.

    The real Ollama llava / gpt-4o response shape matches this exactly:
    a single OpenAI-style choice with a JSON-formatted content string.
    The example uses a smaller transaction set than example 02 to make
    it visually obvious which path produced the result.
    """
    # Note the deliberate hallucination: the vision model "saw" only
    # 4 out of 11 rows (low-resolution scan) AND mis-OCR'd one number
    # (89.50 became 8.50). The Golden Rule should catch this and flag
    # the statement as Unverified.
    payload = {
        "account_id": "12345678",
        "currency": "GBP",
        "opening_balance": "1500.00",
        "closing_balance": "2621.59",
        "transactions": [
            {"booking_date": "2026-04-01", "description": "SALARY ACME CORP",       "amount": 2500.00, "confidence": 0.88},
            {"booking_date": "2026-04-01", "description": "STANDING ORDER RENT",   "amount": -1200.00, "confidence": 0.92},
            {"booking_date": "2026-04-04", "description": "DIRECT DEBIT BRITISH GAS", "amount": -8.50, "confidence": 0.41},
            {"booking_date": "2026-04-08", "description": "CARD PAYMENT COFFEE",   "amount": -3.85,    "confidence": 0.96},
        ],
    }
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def main() -> int:
    if not SAMPLE_PDF.exists():
        print(
            "Sample scan not found. Run first:\n"
            "  python examples/hybrid/generate_sample_pdfs.py",
            file=sys.stderr,
        )
        return 1

    print(f"Input: {SAMPLE_PDF.relative_to(REPO_ROOT)}")
    print()

    # Step 1 — show why the orchestrator picks the vision path.
    try:
        extracted = pdf_text.extract_text(SAMPLE_PDF)
    except Exception as exc:
        extracted = ""
        print(f"  pypdf could not extract any text: {exc}")
    char_count = len(extracted.strip())
    print(f"  pypdf text density:        {char_count} chars")
    print(f"  LOW_TEXT_DENSITY_THRESHOLD: {LOW_TEXT_DENSITY_THRESHOLD}")
    print(f"  decision:                   {'route to vision' if char_count < LOW_TEXT_DENSITY_THRESHOLD else 'stay on text-LLM'}")
    print()

    live = bool(os.environ.get("BSP_HYBRID_VISION_MODEL"))
    mode = "LIVE" if live else "MOCK"
    print(f"Mode: {mode}")
    if live:
        print(f"Model: {os.environ.get('BSP_HYBRID_VISION_MODEL')}")
    else:
        print("Set BSP_HYBRID_VISION_MODEL=ollama/llava (and run `ollama serve`)")
        print("to call a real multimodal model instead of the mock.")
    print()

    if live:
        # Real run: VisionExtractor reads the env var.
        vision = VisionExtractor()
    else:
        # Mock run: inject a stubbed completion + a fake pypdfium2 module
        # so this example doesn't need pypdfium2 installed at all.
        _install_fake_pdfium()
        vision = VisionExtractor(
            model="mock/llava",
            completion_fn=_mock_vision_completion,
        )

    result = smart_ingest(SAMPLE_PDF, vision_extractor=vision)

    print(f"  Source method:    {result.source_method}")
    print(f"  Source format:    {result.source_format}")
    print(f"  Transactions:     {len(result.transactions)}")
    if result.verification:
        v = result.verification
        print(f"  Verification:     {v.status.value.upper()}")
        print(f"    expected delta: {v.expected_delta}")
        print(f"    actual delta:   {v.actual_delta}")
        print(f"    discrepancy:    {v.discrepancy}")
        print(f"    message:        {v.message}")
    print(f"  Warnings:         {result.warnings or '(none)'}")
    print()

    print("Extracted rows:")
    for tx in result.transactions:
        booking = tx.booking_date.isoformat() if tx.booking_date else ""
        conf = f"{tx.confidence:.2f}" if tx.confidence is not None else ""
        flag = " <-- LOW CONFIDENCE" if (tx.confidence or 1.0) < 0.6 else ""
        print(
            f"  {booking}  {str(tx.amount):>10}  conf={conf}  "
            f"{(tx.description or '')[:36]}{flag}"
        )
    print()
    print("Notice the discrepancy + the low-confidence row. In production")
    print("this is your cue to flag the statement 'Unverified' and queue")
    print("it for human review (the v0.0.6 review mode UI).")
    return 0


def _install_fake_pdfium() -> None:
    """Insert a stub pypdfium2 module so the mock run needs no extras."""
    import sys as _sys
    import types

    if "pypdfium2" in _sys.modules:
        return

    fake = types.ModuleType("pypdfium2")

    class _Bitmap:
        def to_pil(self) -> Any:
            class _PilLike:
                def save(self, buffer: Any, format: str) -> None:  # noqa: A002
                    buffer.write(b"PNG_BYTES")

            return _PilLike()

    class _Page:
        def render(self, scale: float) -> _Bitmap:  # noqa: ARG002
            return _Bitmap()

    class _PdfDocument:
        def __init__(self, _path: str) -> None:
            pass

        def __len__(self) -> int:
            return 1

        def __getitem__(self, _index: int) -> _Page:
            return _Page()

    fake.PdfDocument = _PdfDocument  # type: ignore[attr-defined]
    _sys.modules["pypdfium2"] = fake


if __name__ == "__main__":
    sys.exit(main())
