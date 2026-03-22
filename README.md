# Bank Statement Parser

Parse CAMT and PAIN.001 XML files, bank CSV files, OFX/QFX statements,
and MT940 statements. Export structured data. Process ZIP archives safely
without extracting every file to disk.

[![PyPI](https://img.shields.io/pypi/pyversions/bankstatementparser.svg?style=for-the-badge)](https://pypi.org/project/bankstatementparser/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/bankstatementparser.svg?style=for-the-badge)](https://pypi.org/project/bankstatementparser/)
[![Codecov](https://img.shields.io/codecov/c/github/sebastienrousseau/bankstatementparser?style=for-the-badge)](https://codecov.io/github/sebastienrousseau/bankstatementparser?branch=main)
[![License](https://img.shields.io/github/license/sebastienrousseau/bankstatementparser?style=for-the-badge)](LICENSE)

## What It Does

- Parse CAMT bank statements with `CamtParser`
- Parse SEPA PAIN.001 payment files with `Pain001Parser`
- Parse bank CSV files with `CsvStatementParser`
- Parse OFX and QFX files with `OfxParser` and `QfxParser`
- Parse MT940 files with `Mt940Parser`
- Auto-detect statement formats with `detect_statement_format(...)` and `create_parser(...)`
- Parse CAMT XML from memory with `from_string(...)` and `from_bytes(...)`
- Read XML entries from ZIP archives with `iter_secure_xml_entries(...)`
- Export results to CSV and JSON
- Stream large files incrementally

## Requirements

- Python `3.9` to `3.12`
- Poetry for local development

## Install

### Package

```bash
pip install bankstatementparser
```

### Repository

#### macOS

```bash
git clone https://github.com/sebastienrousseau/bankstatementparser.git
cd bankstatementparser
python3 -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install --with dev
```

#### Linux

```bash
git clone https://github.com/sebastienrousseau/bankstatementparser.git
cd bankstatementparser
python3 -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install --with dev
```

#### WSL

```bash
git clone https://github.com/sebastienrousseau/bankstatementparser.git
cd bankstatementparser
python3 -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install --with dev
```

## First Run

### Parse a CAMT file

```python
from bankstatementparser import CamtParser

parser = CamtParser("tests/test_data/camt.053.001.02.xml")
transactions = parser.parse()
print(transactions.head())
```

### Parse a PAIN.001 file

```python
from bankstatementparser import Pain001Parser

parser = Pain001Parser("tests/test_data/pain.001.001.03.xml")
payments = parser.parse()
print(payments.head())
```

### Auto-detect the statement format

```python
from bankstatementparser import create_parser, detect_statement_format

file_name = "tests/test_data/sample.ofx"
format_name = detect_statement_format(file_name)
parser = create_parser(file_name, format_name)
records = parser.parse()
print(format_name, records.head())
```

### Parse CAMT XML from memory

```python
from bankstatementparser import CamtParser

xml_bytes = open("tests/test_data/camt.053.001.02.xml", "rb").read()
parser = CamtParser.from_bytes(xml_bytes, source_name="statement.xml")
transactions = parser.parse()
```

Use `from_string(...)` or `from_bytes(...)` only with decompressed XML
content. Do not pass raw ZIP archive bytes to the parser.

### Parse XML files inside a ZIP archive

```python
from bankstatementparser import CamtParser, iter_secure_xml_entries

for entry in iter_secure_xml_entries("statements.zip"):
    parser = CamtParser.from_bytes(
        entry.xml_bytes,
        source_name=entry.source_name,
    )
    transactions = parser.parse()
    print(entry.source_name, len(transactions))
```

`iter_secure_xml_entries(...)` rejects encrypted entries, enforces size
limits, and blocks suspicious compression ratios before parsing.

## Command Line

Run the CLI as a module:

```bash
python -m bankstatementparser.cli --type camt --input ./tests/test_data/camt.053.001.02.xml
```

Export CAMT output:

```bash
python -m bankstatementparser.cli \
  --type camt \
  --input ./tests/test_data/camt.053.001.02.xml \
  --output ./example-output/camt.csv
```

Export PAIN.001 output:

```bash
python -m bankstatementparser.cli \
  --type pain001 \
  --input ./tests/test_data/pain.001.001.03.xml \
  --output ./example-output/pain001.csv
```

## Streaming

Stream CAMT transactions:

```python
from bankstatementparser import CamtParser

parser = CamtParser("tests/test_data/camt.053.001.02.xml")
for transaction in parser.parse_streaming(redact_pii=True):
    print(transaction)
    break
```

Stream PAIN.001 payments:

```python
from bankstatementparser import Pain001Parser

parser = Pain001Parser("tests/test_data/pain.001.001.03.xml")
for payment in parser.parse_streaming(redact_pii=True):
    print(payment)
    break
```

## Examples

See [examples/README.md](examples/README.md) for runnable examples covering:

- basic CAMT parsing
- CAMT inspection
- CAMT export
- CAMT streaming
- secure ZIP processing
- basic PAIN.001 parsing
- auto-detected CSV, OFX/QFX, MT940, CAMT, and PAIN.001 parsing
- PAIN.001 export
- PAIN.001 streaming
- compatibility wrappers
- CLI usage

## Project Layout

```text
bankstatementparser/  Package code
docs/                 Compliance and validation docs
examples/             Runnable examples
scripts/              Supply-chain and release tooling
tests/                Unit and integration tests
```

## Verify the Repository

Run the full local validation suite:

```bash
ruff check bankstatementparser tests examples scripts
python -m mypy bankstatementparser
python -m pytest
bandit -r bankstatementparser examples scripts -q
pip-audit --cache-dir /tmp/pip-audit-cache
```

## Security

Bank statement files can contain sensitive financial and personal data.

- See [SECURITY.md](SECURITY.md)
- See [VULNERABILITY_REPORTING.md](VULNERABILITY_REPORTING.md)
- See [docs/compliance/SOFTWARE_VALIDATION_PROCEDURE.md](docs/compliance/SOFTWARE_VALIDATION_PROCEDURE.md)
- See [docs/compliance/TRACEABILITY_MATRIX.md](docs/compliance/TRACEABILITY_MATRIX.md)

## Contributing

Signed commits are required.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

See [LICENSE](LICENSE).
