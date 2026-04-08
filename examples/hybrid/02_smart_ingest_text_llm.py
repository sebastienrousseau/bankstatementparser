"""
Example 02 — Path B: text-LLM extraction for digital PDFs.

Demonstrates `smart_ingest()` falling through to the text-LLM path
when given a digital (text-layer) PDF that no deterministic parser
can handle.

The example runs in one of two modes:

  LIVE   (default if `BSP_HYBRID_MODEL` is set)
         Calls a real LiteLLM-supported backend. Default model is
         `ollama/llama3` (set BSP_HYBRID_MODEL=ollama/llama3).
         Make sure `ollama serve` is running and you've pulled the
         model: `ollama pull llama3`.

  MOCK   (default if no env var is set)
         Replaces the LiteLLM completion call with a deterministic
         stub so the example always runs end-to-end without
         downloading any model. Useful for CI, smoke tests, and
         "show me how it works" demos.

Prerequisites:
    pip install 'bankstatementparser[hybrid]'
    python examples/hybrid/generate_sample_pdfs.py

Run:
    python examples/hybrid/02_smart_ingest_text_llm.py

Cross-platform: macOS / Linux / WSL identical. On WSL, point Ollama
at the Windows host with BSP_HYBRID_API_BASE=http://host.docker.internal:11434
if you're running Ollama on Windows instead of inside WSL.
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
    LLMExtractor,
    smart_ingest,
)

EXAMPLE_DIR = Path(__file__).resolve().parent
SAMPLE_PDF = EXAMPLE_DIR / "sample_data" / "digital.pdf"


# ---------------------------------------------------------------------------
# Mock LLM — used when BSP_HYBRID_MODEL is not set
# ---------------------------------------------------------------------------


def _mock_completion(**kwargs: Any) -> dict[str, Any]:
    """Return a fixed JSON payload that matches sample_data/digital.pdf.

    A real LLM produces something equivalent for the same statement;
    using a stub here lets the example run offline and in CI.
    """
    payload = {
        "account_id": "12345678",
        "currency": "GBP",
        "opening_balance": "1500.00",
        "closing_balance": "2621.59",
        "transactions": [
            {"booking_date": "2026-04-01", "description": "SALARY ACME CORP",                 "amount": 2500.00, "reference": None,        "confidence": 0.99},
            {"booking_date": "2026-04-01", "description": "STANDING ORDER RENT",              "amount": -1200.00, "reference": "SO-RENT",  "confidence": 0.99},
            {"booking_date": "2026-04-02", "description": "CARD PAYMENT 12:49 COFFEE SHOP",   "amount": -3.85,    "reference": None,        "confidence": 0.95},
            {"booking_date": "2026-04-02", "description": "AMZN MKTPLACE 2026-04-02 #A1B2C3", "amount": -29.99,   "reference": "A1B2C3",    "confidence": 0.97},
            {"booking_date": "2026-04-03", "description": "CONTACTLESS TFL TRAVEL",            "amount": -7.40,    "reference": None,        "confidence": 0.96},
            {"booking_date": "2026-04-03", "description": "REFUND ZARA RETURNS",               "amount": 39.95,    "reference": "RFD-001",   "confidence": 0.94},
            {"booking_date": "2026-04-04", "description": "DIRECT DEBIT BRITISH GAS",         "amount": -89.50,   "reference": "DD-GAS",    "confidence": 0.98},
            {"booking_date": "2026-04-05", "description": "AMZN MKTPLACE 2026-04-05 #Z9Y8X7", "amount": -29.99,   "reference": "Z9Y8X7",    "confidence": 0.97},
            {"booking_date": "2026-04-06", "description": "CARD PAYMENT 19:02 SAINSBURYS",    "amount": -54.20,   "reference": None,        "confidence": 0.96},
            {"booking_date": "2026-04-07", "description": "INTEREST PAID",                     "amount": 0.42,     "reference": None,        "confidence": 0.99},
            {"booking_date": "2026-04-08", "description": "CARD PAYMENT 08:15 COFFEE SHOP",   "amount": -3.85,    "reference": None,        "confidence": 0.95},
        ],
    }
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}]
    }


def main() -> int:
    if not SAMPLE_PDF.exists():
        print(
            "Sample PDF not found. Run first:\n"
            "  python examples/hybrid/generate_sample_pdfs.py",
            file=sys.stderr,
        )
        return 1

    live = bool(os.environ.get("BSP_HYBRID_MODEL"))
    mode = "LIVE" if live else "MOCK"
    print(f"Mode: {mode}")
    if live:
        print(f"Model: {os.environ.get('BSP_HYBRID_MODEL')}")
    else:
        print("Set BSP_HYBRID_MODEL=ollama/llama3 (and run `ollama serve`)")
        print("to call a real model instead of the mock.")
    print()
    print(f"Input: {SAMPLE_PDF.relative_to(REPO_ROOT)}")
    print()

    extractor = (
        LLMExtractor() if live else LLMExtractor(completion_fn=_mock_completion)
    )

    result = smart_ingest(SAMPLE_PDF, extractor=extractor)

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

    print("All extracted transactions:")
    print()
    print(f"  {'date':<10}  {'amount':>10}  {'conf':>5}  description")
    print(f"  {'-' * 10}  {'-' * 10}  {'-' * 5}  {'-' * 40}")
    for tx in result.transactions:
        booking = tx.booking_date.isoformat() if tx.booking_date else ""
        conf = f"{tx.confidence:.2f}" if tx.confidence is not None else ""
        print(
            f"  {booking:<10}  {str(tx.amount):>10}  {conf:>5}  "
            f"{(tx.description or '')[:40]}"
        )
    print()

    print("Every row is tagged source_method='llm' for audit purposes,")
    print("and `raw_source_text` is populated where the description was")
    print("found in the original PDF text — ready for v0.0.6 review mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
