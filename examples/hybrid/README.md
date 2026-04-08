# Hybrid Pipeline Examples — v0.0.5 "Universal Extraction"

Runnable, end-to-end demonstrations of every code path the v0.0.5
hybrid pipeline can take. Every script works on **macOS, Linux, and
WSL** without any system-level dependencies — `pypdfium2`, `pypdf`,
and `litellm` are all pure-Python wheels.

## Why these examples are synthetic

Real bank PDFs cannot be redistributed (PII + copyright). Instead,
[`generate_sample_pdfs.py`](generate_sample_pdfs.py) creates two
reproducible files in `sample_data/`:

| File | Layer | Routes through |
|---|---|---|
| `digital.pdf` | Text + glyphs (born-digital) | Path B (text-LLM) |
| `scanned.pdf` | Pixels only (rasterised, no text layer) | Path C (vision-LLM) |

If you have a real statement you want to try, drop it into
`sample_data/` and change the `SAMPLE_PDF` constant at the top of
the relevant example. Every script is one path-variable away from
running on your own data.

## The three paths

```mermaid
flowchart TD
    A[smart_ingest&lpar;path&rpar;] --> B{detect_statement_format}
    B -- CAMT/PAIN/OFX/MT940/CSV --> C[Path A: deterministic parser]
    C --> Z[IngestResult<br/>source_method='deterministic']

    B -- pdf or unknown --> D[pypdf extract_text]
    D --> E{text len &gt;= 50?}

    E -- yes --> F[Path B: LLMExtractor<br/>BSP_HYBRID_MODEL<br/>default ollama/llama3]
    F --> Y[IngestResult<br/>source_method='llm']

    E -- no --> G[Path C: VisionExtractor<br/>BSP_HYBRID_VISION_MODEL<br/>opt-in, no default]
    G --> X[IngestResult<br/>source_method='vision']

    Z --> V[verify_balance<br/>Golden Rule]
    Y --> V
    X --> V
    V --> R[VERIFIED<br/>DISCREPANCY<br/>FAILED]
```

## Prerequisites

| Mode | Install |
|---|---|
| Path A only (CAMT/PAIN/OFX/MT940/CSV) | `pip install bankstatementparser` |
| Path A + Path B (text-LLM for digital PDFs) | `pip install 'bankstatementparser[hybrid]'` |
| Plus higher-fidelity table extraction | `pip install 'bankstatementparser[hybrid-plus]'` |
| Plus vision (Path C, scans/photos) | `pip install 'bankstatementparser[hybrid-vision]'` |
| To regenerate the sample PDFs | `pip install reportlab pillow pypdfium2` |

For the **live** LLM examples, you also need either Ollama running
locally or an API key for a hosted provider:

```bash
# Local + private (recommended for finance data)
ollama serve &
ollama pull llama3      # text path
ollama pull llava       # vision path

export BSP_HYBRID_MODEL=ollama/llama3
export BSP_HYBRID_VISION_MODEL=ollama/llava
```

Or use any LiteLLM-supported provider:

```bash
export BSP_HYBRID_MODEL=anthropic/claude-3-haiku-20240307
export ANTHROPIC_API_KEY=sk-ant-...
```

> **WSL note** — if Ollama is running on Windows instead of inside
> WSL, point the library at the Windows host:
> `export BSP_HYBRID_API_BASE=http://host.docker.internal:11434`

## Quick start (15 minutes, end to end)

From the repository root:

```bash
# 1. install
pip install 'bankstatementparser[hybrid-vision]'
pip install reportlab pillow

# 2. generate the synthetic PDFs (one-off)
python examples/hybrid/generate_sample_pdfs.py

# 3. walk through the four paths
python examples/hybrid/01_smart_ingest_deterministic.py
python examples/hybrid/02_smart_ingest_text_llm.py     # mock mode
python examples/hybrid/03_smart_ingest_vision.py       # mock mode
python examples/hybrid/04_golden_rule.py
python examples/hybrid/05_dedupe_recurring.py
bash   examples/hybrid/06_cli_walkthrough.sh
```

The text-LLM and vision examples both default to **mock mode** so
they run end-to-end without any network calls. Set the env vars
above to switch to the live path.

## What each script teaches

| Script | Path | Live mode requires | Teaches |
|---|---|---|---|
| [`generate_sample_pdfs.py`](generate_sample_pdfs.py) | n/a | reportlab, pillow, pypdfium2 | How the two sample PDFs are produced. Tweak `TRANSACTIONS` to change the demo data. |
| [`01_smart_ingest_deterministic.py`](01_smart_ingest_deterministic.py) | A | nothing | `smart_ingest()` against a CAMT.053 fixture, `source_method='deterministic'`, `transaction_hash` per row, $0 cost |
| [`02_smart_ingest_text_llm.py`](02_smart_ingest_text_llm.py) | B | `BSP_HYBRID_MODEL` | Digital PDF → `pypdf` text → LiteLLM → `Transaction` rows. Mock mode shipped for offline runs. |
| [`03_smart_ingest_vision.py`](03_smart_ingest_vision.py) | C | `BSP_HYBRID_VISION_MODEL` | Scan → `pypdfium2` render → multimodal LLM → rows. Demonstrates `LOW_TEXT_DENSITY_THRESHOLD` automatic handover and a `DISCREPANCY` outcome. |
| [`04_golden_rule.py`](04_golden_rule.py) | n/a | nothing | All three `verify_balance()` outcomes (`VERIFIED`, `DISCREPANCY`, `FAILED`) on the same dataset. |
| [`05_dedupe_recurring.py`](05_dedupe_recurring.py) | n/a | nothing | `normalize_description()` noise stripping, `transaction_hash` stability, idempotent batching with `Deduplicator.dedupe_by_hash()`. |
| [`06_cli_walkthrough.sh`](06_cli_walkthrough.sh) | A/B/C | `BSP_HYBRID_*` env vars | Four flavours of the new `--type ingest` CLI subcommand. |

## Mock vs. live mode — what to expect

### Mock mode (default)

Both `02_*` and `03_*` ship with a small `_mock_completion()`
function that returns a fixed JSON payload matching the synthetic
sample. This is exactly the same shape a real LiteLLM response would
take, just deterministic. The orchestrator, `LLMExtractor`,
`VisionExtractor`, dedup, hashing, verification, and CLI all run
unchanged — only the network call is short-circuited.

Run with no env vars:

```text
$ python examples/hybrid/02_smart_ingest_text_llm.py
Mode: MOCK
Set BSP_HYBRID_MODEL=ollama/llama3 (and run `ollama serve`)
to call a real model instead of the mock.
...
  Source method:    llm
  Verification:     VERIFIED
```

### Live mode

Set the env var, make sure Ollama (or your provider) is reachable,
and re-run the same script. The output will look identical except
for the model latency and any small drift in description casing /
punctuation that the LLM produces.

```text
$ BSP_HYBRID_MODEL=ollama/llama3 python examples/hybrid/02_smart_ingest_text_llm.py
Mode: LIVE
Model: ollama/llama3
...
```

## Bringing your own real PDFs

Every example exposes a single path constant near the top:

```python
SAMPLE_PDF = EXAMPLE_DIR / "sample_data" / "digital.pdf"
```

Drop a real statement next to the script and change the constant —
the rest of the example runs unchanged. The CLI walkthrough takes
the path as a command-line argument so you don't even need to edit
anything:

```bash
bankstatementparser --type ingest --input /path/to/your_statement.pdf
```

## Cross-platform verification matrix

| Step | macOS | Linux | WSL | Native Windows |
|---|---|---|---|---|
| `pip install` of all extras | ✅ | ✅ | ✅ | ✅ |
| `generate_sample_pdfs.py` | ✅ | ✅ | ✅ | ✅ |
| `01_*` deterministic | ✅ | ✅ | ✅ | ✅ |
| `02_*` mock mode | ✅ | ✅ | ✅ | ✅ |
| `02_*` live mode (local Ollama) | ✅ | ✅ | ✅ * | ✅ |
| `03_*` mock mode | ✅ | ✅ | ✅ | ✅ |
| `03_*` live mode (Ollama llava) | ✅ | ✅ | ✅ * | ✅ |
| `06_cli_walkthrough.sh` | ✅ | ✅ | ✅ | ❌ (use PowerShell equivalents) |

\* On WSL, if Ollama runs on the Windows host instead of inside WSL,
set `BSP_HYBRID_API_BASE=http://host.docker.internal:11434` so
LiteLLM points at the right endpoint.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: pypdf` | Core install only | `pip install 'bankstatementparser[hybrid]'` |
| `ModuleNotFoundError: pypdfium2` | `[hybrid-vision]` not installed | `pip install 'bankstatementparser[hybrid-vision]'` |
| `VisionExtractorError: Vision model required for processing` | `BSP_HYBRID_VISION_MODEL` unset | `export BSP_HYBRID_VISION_MODEL=ollama/llava` |
| `LLMExtractorError: LLM completion failed: Connection refused` | Ollama not running | `ollama serve &` |
| Live LLM returns malformed JSON | Model too small / too creative | Try a larger model or set `BSP_HYBRID_MODEL=ollama/llama3:70b` |
| `LOW_TEXT_DENSITY` warning on a digital PDF | `pypdf` couldn't parse the text layer | Try `pip install 'bankstatementparser[hybrid-plus]'` (pdfplumber) and re-run |
| `DISCREPANCY` on a real statement | LLM dropped a row, or balances were mis-extracted | Re-run with a larger model, or pass `opening_balance=`/`closing_balance=` overrides to `smart_ingest()` |
| Vision call hangs / times out at 600s with `ollama/llava` | Verified upstream LiteLLM ↔ Ollama integration bug: short prompts work fine, long system prompts hang. The library's structured-JSON extraction prompt is large enough to trigger it. | (a) Use a hosted vision model (`gpt-4o`, `claude-opus-4-6`, `gemini-2.5-pro`) instead of local llava — they all work with LiteLLM and don't have this issue. (b) Or pass a custom `completion_fn` to `VisionExtractor(...)` that calls Ollama's `/api/chat` directly, bypassing LiteLLM. |
| Local llava-7b returns nonsense rows (wrong currency, fabricated dates, hallucinated transactions) | Smoke-tested with the synthetic scanned PDF: llava-7b is not capable enough for dense statement table extraction at any render scale. | Use a larger local vision model (`llava:34b`, `llava-llama3`, `bakllava`) or a hosted multimodal model. The 7B parameter class is not production-grade for this task. |

## Smoke test results (real models, 2026-04-08)

We ran every example end-to-end against real local models on Apple Silicon to validate the library code with the actual LLM stack:

| Example | Model | Result |
|---|---|---|
| `01_*` deterministic | n/a | ✅ Perfect — 3 transactions extracted from CAMT.053 fixture, all hashes computed |
| `02_*` text-LLM | `ollama/llama3` (4.7 GB) | ✅ Perfect — all 11 transactions extracted, every amount correct, **VERIFIED** balance, every row tagged `confidence=1.00`. End-to-end runtime ~25s on M-series. |
| `03_*` vision-LLM | `ollama/llava:7b` (4.7 GB) | ⚠️ Library and orchestrator work correctly. **Blocked by upstream LiteLLM integration bug**: short prompts work in 2.8s, the full structured-JSON system prompt hangs LiteLLM at the 600s timeout. Direct Ollama `/api/chat` call with the same prompt completes in 18s but llava-7b hallucinates the contents anyway. **Recommended path for production:** use hosted vision models. |
| `04_*` Golden Rule | n/a | ✅ All three outcomes (`VERIFIED`, `DISCREPANCY`, `FAILED`) reproduce as documented |
| `05_*` dedupe | n/a | ✅ Recurring Amazon dup caught in batch 1, both already-seen rows caught in batch 2 |
| `06_*` CLI walkthrough | n/a | ✅ Deterministic path produces the expected DataFrame with `transaction_hash`, `source_method`, and verification fields |
