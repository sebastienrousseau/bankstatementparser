#!/usr/bin/env bash
# Example 06 — CLI walkthrough for the v0.0.5 `--type ingest` subcommand.
#
# Cross-platform: this script runs on macOS, Linux, and WSL. On native
# Windows, run the equivalent commands in PowerShell — the Python CLI
# itself is platform-agnostic.
#
# Prerequisites:
#   pip install 'bankstatementparser[hybrid-vision]'
#   python examples/hybrid/generate_sample_pdfs.py
#
# Optional (only required for the live LLM commands):
#   ollama serve &
#   ollama pull llama3
#   ollama pull llava
#
# Run the whole walkthrough:
#   bash examples/hybrid/06_cli_walkthrough.sh

set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${EXAMPLE_DIR}/../.." && pwd)"
SAMPLE_DIR="${EXAMPLE_DIR}/sample_data"
DIGITAL_PDF="${SAMPLE_DIR}/digital.pdf"
SCANNED_PDF="${SAMPLE_DIR}/scanned.pdf"
CAMT_FIXTURE="${REPO_ROOT}/tests/test_data/camt.053.001.02.xml"

cd "${REPO_ROOT}"

banner() {
  printf '\n========================================================\n'
  printf '%s\n' "$1"
  printf '========================================================\n'
}

banner "1) Path A — Deterministic CAMT.053 (free, fastest)"
echo "Command:"
echo "  bankstatementparser --type ingest --input ${CAMT_FIXTURE#${REPO_ROOT}/}"
echo
bankstatementparser --type ingest --input "${CAMT_FIXTURE}" || true

banner "2) Path B — Text-LLM on a digital PDF"
if [[ -z "${BSP_HYBRID_MODEL:-}" ]]; then
  echo "Skipped: set BSP_HYBRID_MODEL=ollama/llama3 (and run \`ollama serve\`)"
  echo "to call a real model. Without it, the CLI cannot fall through to"
  echo "the live LLM path. The mock-mode example is in 02_smart_ingest_text_llm.py."
else
  if [[ ! -f "${DIGITAL_PDF}" ]]; then
    echo "Generating sample PDFs first..."
    python "${EXAMPLE_DIR}/generate_sample_pdfs.py"
  fi
  echo "Command:"
  echo "  bankstatementparser --type ingest --input ${DIGITAL_PDF#${REPO_ROOT}/}"
  echo
  bankstatementparser --type ingest --input "${DIGITAL_PDF}"
fi

banner "3) Path C — Vision-LLM on a scanned PDF"
if [[ -z "${BSP_HYBRID_VISION_MODEL:-}" ]]; then
  echo "Skipped: set BSP_HYBRID_VISION_MODEL=ollama/llava (and run \`ollama serve\`)"
  echo "to call a real multimodal model. Without it, the CLI raises a"
  echo "VisionExtractorError telling you exactly what to set."
  echo
  echo "You can still observe the error path:"
  echo "  bankstatementparser --type ingest --input ${SCANNED_PDF#${REPO_ROOT}/}"
  echo "  -> Error: Vision model required for processing. Set BSP_HYBRID_VISION_MODEL..."
else
  if [[ ! -f "${SCANNED_PDF}" ]]; then
    echo "Generating sample PDFs first..."
    python "${EXAMPLE_DIR}/generate_sample_pdfs.py"
  fi
  echo "Command:"
  echo "  bankstatementparser --type ingest --input ${SCANNED_PDF#${REPO_ROOT}/}"
  echo
  bankstatementparser --type ingest --input "${SCANNED_PDF}"
fi

banner "4) Write the unified ledger straight to CSV"
OUT_CSV="${SAMPLE_DIR}/out.csv"
mkdir -p "${SAMPLE_DIR}"
echo "Command:"
echo "  bankstatementparser --type ingest --input <file> --output ${OUT_CSV#${REPO_ROOT}/}"
echo
bankstatementparser \
  --type ingest \
  --input "${CAMT_FIXTURE}" \
  --output "${OUT_CSV}"
echo
echo "First 6 rows of the CSV:"
head -6 "${OUT_CSV}"

banner "Done"
echo "Inspect the columns: transaction_hash, source_method, booking_date,"
echo "description, amount, currency, reference, confidence."
echo
echo "All rows can be safely re-imported into a downstream system —"
echo "the transaction_hash column is the idempotent dedupe key."
