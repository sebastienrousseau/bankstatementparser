# Bank Statement Parser

Parse CAMT (ISO 20022), SEPA Pain.001, CSV, OFX/QFX, and MT940 bank
statements into pandas DataFrames — with deterministic parsing first
and an optional hybrid LLM pipeline for PDFs.

## Install

```bash
pip install bankstatementparser

# With Excel export support
pip install 'bankstatementparser[excel]'
```

## Quick start

```python
from bankstatementparser import CamtParser

parser = CamtParser("statement.xml")
transactions = parser.get_transactions()
balances = parser.get_account_balances()
```

Auto-detect the format instead of naming a parser:

```python
from bankstatementparser import create_parser

parser = create_parser("statement.ofx")
summary = parser.get_summary()
```

## Where to go next

- [XML Field Mapping](MAPPING.md) — how ISO 20022 XML elements map
  to DataFrame columns.
- [API Reference](api/camt_parser.md) — generated from the source
  docstrings.
- [Compliance](compliance/CHANGE_CONTROL_PROCEDURE.md) — validation
  and change-control documentation.
- [Changelog](https://github.com/sebastienrousseau/bankstatementparser/blob/main/CHANGELOG.md)
  — release notes, including breaking-change migration guides.
