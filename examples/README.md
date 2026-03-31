# Examples

These examples are runnable directly from a repository checkout and use the
real ISO 20022 fixtures under `tests/test_data/`.

- `parse_camt_basic.py`: basic CAMT.053 parsing
- `parse_camt_from_string.py`: parse CAMT.053 from an in-memory XML string
- `inspect_camt.py`: balances, transactions, statement stats, and summary
- `export_camt.py`: export CAMT output to CSV and JSON
- `export_camt_excel.py`: export CAMT transactions to an Excel workbook
- `stream_camt.py`: incremental CAMT transaction parsing
- `parse_camt_zip.py`: parse separate CAMT XML files from a ZIP archive without extraction
- `parse_detected_formats.py`: auto-detect CSV, OFX/QFX, MT940, CAMT, and PAIN.001
- `parse_pain001_basic.py`: basic PAIN.001 parsing
- `export_pain001.py`: export PAIN.001 output to CSV and JSON
- `stream_pain001.py`: incremental PAIN.001 payment parsing
- `validate_input.py`: validate file paths before parsing with InputValidator
- `compatibility_wrappers.py`: legacy wrapper APIs from `bank_statement_parsers.py`
- `cli_examples.sh`: CLI commands for CAMT and PAIN.001

The CAMT ZIP example uses `tests/test_data/camt.053.001.02.xml`, which is a
real ISO 20022 CAMT.053 bank statement format.

The ZIP example uses `bankstatementparser.iter_secure_xml_entries(...)` so it
demonstrates the same hardened ZIP member validation that the library exposes
for production use.
