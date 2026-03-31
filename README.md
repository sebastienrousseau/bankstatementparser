# Bank Statement Parser

Parse bank statements across six formats — CAMT, PAIN.001, CSV, OFX/QFX, and MT940 — into structured DataFrames. Process ZIP archives safely. Redact PII by default. Stream files of any size.

Built for finance teams, treasury analysts, and fintech developers who need reliable, auditable extraction from ISO 20022 and legacy banking formats without sending data to external services.

[![PyPI](https://img.shields.io/pypi/pyversions/bankstatementparser.svg?style=for-the-badge)](https://pypi.org/project/bankstatementparser/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/bankstatementparser.svg?style=for-the-badge)](https://pypi.org/project/bankstatementparser/)
[![Codecov](https://img.shields.io/codecov/c/github/sebastienrousseau/bankstatementparser?style=for-the-badge)](https://codecov.io/github/sebastienrousseau/bankstatementparser?branch=main)
[![License](https://img.shields.io/github/license/sebastienrousseau/bankstatementparser?style=for-the-badge)](LICENSE)

## Key Features

| Feature | Description |
|---|---|
| **6 formats** | CAMT.053, PAIN.001, CSV, OFX, QFX, MT940 |
| **Auto-detection** | `detect_statement_format()` identifies the format; `create_parser()` returns the right parser |
| **PII redaction** | Names, IBANs, and addresses masked by default — opt in with `--show-pii` |
| **Streaming** | `parse_streaming()` processes large files incrementally without loading everything into memory |
| **Secure ZIP** | `iter_secure_xml_entries()` rejects zip bombs, encrypted entries, and suspicious compression ratios |
| **In-memory parsing** | `from_string()` and `from_bytes()` parse XML without touching disk |
| **Export** | CSV, JSON, and Excel (`.xlsx`) output |
| **100% coverage** | 442 tests, 100% branch coverage, property-based fuzzing with Hypothesis |

## Requirements

- Python **3.9** through **3.14**
- Poetry (for local development)

## Install

```bash
pip install bankstatementparser
```

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

Process large files without loading everything into memory:

```python
from bankstatementparser import CamtParser

parser = CamtParser("large_statement.xml")
for transaction in parser.parse_streaming():
    process(transaction)  # each transaction is a dict
```

Works with both `CamtParser` and `Pain001Parser`.

## Command Line

```bash
# Parse and display
python -m bankstatementparser.cli --type camt --input statement.xml

# Export to CSV
python -m bankstatementparser.cli --type camt --input statement.xml --output transactions.csv

# Stream with PII visible
python -m bankstatementparser.cli --type camt --input statement.xml --streaming --show-pii
```

Supports `--type camt` and `--type pain001`.

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

## Examples

See [`examples/`](examples/README.md) for 14 runnable scripts:

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

## XML Tag Mapping

See [`docs/MAPPING.md`](docs/MAPPING.md) for a complete reference of ISO 20022 XML tags to DataFrame columns across all six formats. Use this when integrating with ERP systems or building reconciliation pipelines.

## Project Layout

```text
bankstatementparser/   Source code (9 modules, 100% branch coverage)
docs/compliance/       ISO 13485 validation, risk register, traceability
examples/              14 runnable example scripts
scripts/               SBOM generation, checksums, signature verification
tests/                 442 tests (unit, integration, property-based, security)
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
Yes. `parse_streaming()` processes incrementally without loading the full file into memory.

See [FAQ.md](FAQ.md) for the complete FAQ covering data privacy, technical specs, and treasury workflows.
