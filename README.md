# Bank Statement Parser

Parse bank statements across **six structured formats** (CAMT, PAIN.001, CSV, OFX/QFX, MT940) **and PDFs** — both digital and scanned — into a single unified `Transaction` model. ISO 20022 files take the deterministic path; PDFs fall through to a configurable LLM (Ollama by default, any LiteLLM-supported provider) and finally to a multimodal vision model for scanned/photocopied statements.

Built for finance teams, treasury analysts, and fintech developers who need reliable, auditable extraction across the full spectrum of bank statement formats — without sending data to external services unless they explicitly opt in.

[![PyPI](https://img.shields.io/pypi/pyversions/bankstatementparser.svg?style=for-the-badge&v=0.0.5)](https://pypi.org/project/bankstatementparser/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/bankstatementparser.svg?style=for-the-badge)](https://pypi.org/project/bankstatementparser/)
[![Codecov](https://img.shields.io/codecov/c/github/sebastienrousseau/bankstatementparser?style=for-the-badge)](https://codecov.io/github/sebastienrousseau/bankstatementparser?branch=main)
[![License](https://img.shields.io/github/license/sebastienrousseau/bankstatementparser?style=for-the-badge)](LICENSE)

## Key Features

| Feature | Description |
|---|---|
| **6 structured formats** | CAMT.053, PAIN.001, CSV, OFX, QFX, MT940 |
| **Hybrid PDF pipeline** *(v0.0.5)* | `smart_ingest()` routes digital PDFs through a text-LLM and scanned PDFs through a multimodal vision model. Deterministic parsers always tried first ($0 cost). |
| **Local-first LLM** *(v0.0.5)* | Ollama is the default backend; switch to Anthropic, OpenAI, or any LiteLLM provider via `BSP_HYBRID_MODEL`. Vision is opt-in via `BSP_HYBRID_VISION_MODEL` — no surprise downloads. |
| **Golden Rule verification** *(v0.0.5)* | Every result carries `opening + credits − debits == closing` status: `VERIFIED`, `DISCREPANCY`, or `FAILED`. |
| **Idempotent dedup** *(v0.0.5)* | Every `Transaction` carries a stable `transaction_hash` (MD5 of date + normalized description + amount). `Deduplicator.dedupe_by_hash()` makes incremental ingestion safe to re-run. |
| **Auto-detection** | `detect_statement_format()` identifies the format; `create_parser()` returns the right parser |
| **PII redaction** | Names, IBANs, and addresses masked by default — opt in with `--show-pii` |
| **Streaming** | `parse_streaming()` at 27,000+ tx/s (CAMT) and 52,000+ tx/s (PAIN.001) with bounded memory |
| **Parallel** | `parse_files_parallel()` for multi-file batch processing across CPU cores |
| **Secure ZIP** | `iter_secure_xml_entries()` rejects zip bombs, encrypted entries, and suspicious compression ratios |
| **In-memory parsing** | `from_string()` and `from_bytes()` parse XML without touching disk |
| **Export** | CSV, JSON, Excel (`.xlsx`), and optional Polars DataFrames |
| **100% coverage** | 541 tests, 100% branch coverage, property-based fuzzing with Hypothesis |

## Requirements

- Python **3.9** through **3.14**
- Poetry (for local development)

## Install

```bash
# Core install — deterministic parsers only (CAMT, PAIN.001, CSV, OFX, QFX, MT940)
pip install bankstatementparser

# Add the text-LLM path for digital PDFs (litellm + pypdf)
pip install 'bankstatementparser[hybrid]'

# Add higher-fidelity table extraction (adds pdfplumber)
pip install 'bankstatementparser[hybrid-plus]'

# Add the multimodal vision path for scanned/photocopied PDFs (adds pypdfium2)
pip install 'bankstatementparser[hybrid-vision]'
```

The core install has zero AI dependencies. Every `[hybrid*]` extra is opt-in and pure-Python — no `poppler`, no system libraries, no GPU required.

### Local Development

Clone and install on **macOS, Linux, or WSL**:

```bash
git clone https://github.com/sebastienrousseau/bankstatementparser.git
cd bankstatementparser
python3 -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install --with dev
```

## Quick Start

### Parse a CAMT statement

```python
from bankstatementparser import CamtParser

parser = CamtParser("statement.xml")
transactions = parser.parse()
print(transactions)
```

```text
   Amount Currency DrCr  Debtor Creditor      ValDt      AccountId
 105678.5      SEK CRDT MUELLER          2010-10-18 50000000054910
-200000.0      SEK DBIT                  2010-10-18 50000000054910
  30000.0      SEK CRDT                  2010-10-18 50000000054910
```

### Parse a PAIN.001 payment file

```python
from bankstatementparser import Pain001Parser

parser = Pain001Parser("payment.xml")
payments = parser.parse()
print(payments)
```

```text
  PmtInfId PmtMtd  InstdAmt Currency  CdtrNm         EndToEndId
  PMT-001  TRF     1500.00  EUR       ACME Corp      E2E-001
  PMT-001  TRF     2300.50  EUR       Global Ltd     E2E-002
```

### Auto-detect the format

```python
from bankstatementparser import create_parser, detect_statement_format

fmt = detect_statement_format("transactions.ofx")
parser = create_parser("transactions.ofx", fmt)
records = parser.parse()
```

Works with `.xml`, `.csv`, `.ofx`, `.qfx`, and `.mt940` files.

### Hybrid extraction (PDFs included) *(v0.0.5)*

`smart_ingest()` is the single entry point that routes any file through the cheapest viable extraction path:

```python
from bankstatementparser.hybrid import smart_ingest

# Path A — deterministic parser (free, fastest, $0)
result = smart_ingest("statement.xml")
print(result.source_method)         # "deterministic"

# Path B — text-LLM for digital PDFs (set BSP_HYBRID_MODEL=ollama/llama3)
result = smart_ingest("statement.pdf")
print(result.source_method)         # "llm"
print(result.verification.status)   # VERIFIED | DISCREPANCY | FAILED

# Path C — multimodal vision for scanned PDFs (set BSP_HYBRID_VISION_MODEL)
# auto-routed when pypdf cannot extract enough text
result = smart_ingest("scan.pdf")
print(result.source_method)         # "vision"
```

Every row carries:

- `source_method` — `"deterministic"`, `"llm"`, or `"vision"` for full audit provenance
- `transaction_hash` — MD5 fingerprint of `date | normalized_description | amount`, ready for idempotent re-ingestion
- `confidence` — float between 0 and 1 for LLM rows, `None` for deterministic
- `raw_source_text` — best-effort source-text slice for the v0.0.6 review-mode UI

A complete walkthrough with synthetic UK-bank PDFs, mock vs. live mode, and a Mermaid flow diagram lives in [`examples/hybrid/README.md`](examples/hybrid/README.md).

### Parse from memory (no disk I/O)

```python
from bankstatementparser import CamtParser

xml_bytes = download_from_sftp()  # your own function
parser = CamtParser.from_bytes(xml_bytes, source_name="daily.xml")
transactions = parser.parse()
```

Pass only decompressed XML to `from_string()` or `from_bytes()`. For ZIP archives, use `iter_secure_xml_entries()`.

### Parse XML files inside a ZIP archive

```python
from bankstatementparser import CamtParser, iter_secure_xml_entries

for entry in iter_secure_xml_entries("statements.zip"):
    parser = CamtParser.from_bytes(entry.xml_bytes, source_name=entry.source_name)
    transactions = parser.parse()
    print(entry.source_name, len(transactions), "transactions")
```

The iterator enforces size limits, blocks encrypted entries, and rejects suspicious compression ratios before any XML parsing occurs.

## PII Redaction

PII (names, IBANs, addresses) is **redacted by default** in console output and streaming mode.

```python
# Redacted by default
for tx in parser.parse_streaming(redact_pii=True):
    print(tx)  # Names and addresses show as ***REDACTED***

# Opt in to see full data
for tx in parser.parse_streaming(redact_pii=False):
    print(tx)
```

File exports (CSV, JSON, Excel) always contain the full unredacted data.

## Streaming

Process large files incrementally. Memory stays bounded regardless of file size — tested at 50,000 transactions with sub-2x memory scaling.

```python
from bankstatementparser import CamtParser

parser = CamtParser("large_statement.xml")
for transaction in parser.parse_streaming():
    process(transaction)  # each transaction is a dict
```

Works with both `CamtParser` and `Pain001Parser`. PAIN.001 files over 50 MB use chunk-based namespace stripping via a temporary file — the full document is never loaded into memory.

## Performance

| Metric | CAMT | PAIN.001 |
|---|---|---|
| **Throughput** | 27,000+ tx/s | 52,000+ tx/s |
| **Per-transaction latency** | 37 us | 19 us |
| **Time to first result** | < 1 ms | < 2 ms |
| **Memory scaling** | Constant (1K–50K) | Constant (1K–50K) |

Performance is flat from 1,000 to 50,000 transactions. CI enforces minimum TPS and latency thresholds.

## Parallel Parsing

Process multiple files simultaneously across CPU cores:

```python
from bankstatementparser import parse_files_parallel

results = parse_files_parallel([
    "statements/jan.xml",
    "statements/feb.xml",
    "statements/mar.xml",
])

for r in results:
    print(r.path, r.status, len(r.transactions), "rows")
```

Uses `ProcessPoolExecutor` to bypass the GIL. Each file is parsed in its own worker process. Auto-detects format per file, or force with `format_name="camt"`.

## Command Line

After installation a `bankstatementparser` console script is available on `PATH`:

```bash
# Parse and display
bankstatementparser --type camt --input statement.xml

# Export to CSV
bankstatementparser --type camt --input statement.xml --output transactions.csv

# Stream with PII visible
bankstatementparser --type camt --input statement.xml --streaming --show-pii

# v0.0.5 — hybrid pipeline (auto-routes deterministic / text-LLM / vision)
bankstatementparser --type ingest --input statement.pdf
bankstatementparser --type ingest --input statement.pdf --output ledger.csv
```

Supports `--type camt`, `--type pain001`, and `--type ingest` (v0.0.5). The `python -m bankstatementparser.cli ...` invocation form continues to work for parity with older releases.

## Deduplication

Detect duplicate transactions across multiple sources:

```python
from bankstatementparser import CamtParser, Deduplicator

parser = CamtParser("statement.xml")
dedup = Deduplicator()
result = dedup.deduplicate(dedup.from_dataframe(parser.parse()))

print(f"Unique: {len(result.unique_transactions)}")
print(f"Exact duplicates: {len(result.exact_duplicates)}")
print(f"Suspected matches: {len(result.suspected_matches)}")
```

The `Deduplicator` uses deterministic hashing for exact matches and configurable similarity thresholds for suspected matches. Each match group includes a confidence score and reason for auditability.

## Export

```python
parser = CamtParser("statement.xml")
parser.parse()

# CSV
parser.export_csv("output.csv")

# JSON (includes summary + transactions)
parser.export_json("output.json")

# Excel
parser.camt_to_excel("output.xlsx")
```

### Polars (optional)

Convert any parser output to a Polars DataFrame:

```python
polars_df = parser.to_polars()
lazy_df = parser.to_polars_lazy()
```

Install with `pip install bankstatementparser[polars]`.

## Examples

See [`examples/`](examples/README.md) for 22 runnable scripts (14 deterministic + 8 hybrid):

### Deterministic parsers

| Example | What it demonstrates |
|---|---|
| `parse_camt_basic.py` | Load a CAMT.053 file and print transactions |
| `parse_camt_from_string.py` | Parse CAMT from an in-memory XML string |
| `inspect_camt.py` | Extract balances, stats, and summaries |
| `export_camt.py` | Export to CSV and JSON |
| `export_camt_excel.py` | Export to Excel workbook |
| `stream_camt.py` | Stream transactions incrementally |
| `parse_camt_zip.py` | Secure ZIP archive processing |
| `parse_detected_formats.py` | Auto-detect CSV, OFX, MT940, and XML formats |
| `parse_pain001_basic.py` | Parse a PAIN.001 payment file |
| `export_pain001.py` | Export PAIN.001 to CSV and JSON |
| `stream_pain001.py` | Stream payments incrementally |
| `validate_input.py` | Validate file paths with InputValidator |
| `compatibility_wrappers.py` | Legacy API wrappers |
| `cli_examples.sh` | CLI commands for CAMT and PAIN.001 |

### Hybrid pipeline *(v0.0.5)*

| Example | What it demonstrates |
|---|---|
| `hybrid/generate_sample_pdfs.py` | Produce reproducible synthetic UK-bank PDFs (digital + scanned) |
| `hybrid/01_smart_ingest_deterministic.py` | Path A — `smart_ingest()` against a CAMT.053 fixture, $0 cost |
| `hybrid/02_smart_ingest_text_llm.py` | Path B — text-LLM extraction from a digital PDF (mock or live Ollama) |
| `hybrid/03_smart_ingest_vision.py` | Path C — multimodal vision extraction with `LOW_TEXT_DENSITY` auto-routing |
| `hybrid/04_golden_rule.py` | All three `verify_balance()` outcomes |
| `hybrid/05_dedupe_recurring.py` | `normalize_description()` + `dedupe_by_hash()` for idempotent batching |
| `hybrid/06_cli_walkthrough.sh` | Four flavours of the new `--type ingest` CLI subcommand |

See [`examples/hybrid/README.md`](examples/hybrid/README.md) for the full walkthrough including a Mermaid flow diagram, the cross-platform verification matrix, and the Ollama smoke-test results.

## XML Tag Mapping

See [`docs/MAPPING.md`](docs/MAPPING.md) for a complete reference of ISO 20022 XML tags to DataFrame columns across all six formats. Use this when integrating with ERP systems or building reconciliation pipelines.

## Project Layout

```text
bankstatementparser/   Source code (13 modules, 100% branch coverage)
docs/compliance/       ISO 13485 validation, risk register, traceability
examples/              14 runnable example scripts
scripts/               SBOM generation, checksums, signature verification
tests/                 467 tests (unit, integration, property-based, security)
```

## Security

Bank statement files contain sensitive financial and personal data. This library is designed with security as a primary constraint:

- **XXE protection** — `resolve_entities=False`, `no_network=True`, `load_dtd=False`
- **ZIP bomb protection** — compression ratio limits, entry size caps, encrypted entry rejection
- **Path traversal prevention** — dangerous pattern blocklist, symlink resolution
- **PII redaction** — default masking of names, IBANs, and addresses
- **Signed commits** — enforced in CI via GitHub API verification
- **Supply chain** — SHA-256 hash-locked dependencies, CycloneDX SBOM, build provenance attestation

For vulnerability reports, see [SECURITY.md](.github/SECURITY.md).

For the full compliance suite, see [`docs/compliance/`](docs/compliance/).

## Verify the Repository

Run the full validation suite locally:

```bash
ruff check bankstatementparser tests examples scripts
python -m mypy bankstatementparser
python -m pytest
bandit -r bankstatementparser examples scripts -q
```

## Contributing

Signed commits required. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).

## FAQ

**What formats are supported?**
CAMT.053, PAIN.001, CSV, OFX, QFX, and MT940.

**Does any data leave my infrastructure?**
No. Zero network calls. XML parsers enforce `no_network=True`. No cloud, no telemetry.

**Is PII redacted automatically?**
Yes. Names, IBANs, and addresses are masked by default in console output and streaming. File exports retain full data.

**Is the extraction deterministic?**
Yes. Same input produces byte-identical output. Critical for financial auditing.

**Can it handle large files?**
Yes. `parse_streaming()` is tested at 50,000 transactions (~25 MB) with bounded memory. Files over 50 MB use chunk-based streaming.

See [FAQ.md](FAQ.md) for the complete FAQ covering data privacy, technical specs, and treasury workflows.

---

THE ARCHITECT ᛫ Sebastien Rousseau ᛫ https://sebastienrousseau.com
THE ENGINE ᛞ EUXIS ᛫ Enterprise Unified Execution Intelligence System ᛫ https://euxis.co
