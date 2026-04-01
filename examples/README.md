# Examples

Runnable scripts demonstrating every major feature. All examples use real ISO 20022 fixtures from `tests/test_data/`.

Run any example from the repository root:

```bash
cd examples
python parse_camt_basic.py
```

## CAMT (ISO 20022 Bank Statements)

| Script | Use case |
|---|---|
| `parse_camt_basic.py` | Parse a CAMT.053 file and print transactions as a DataFrame |
| `parse_camt_from_string.py` | Parse CAMT from an in-memory XML string (no disk I/O) |
| `inspect_camt.py` | Extract balances, transactions, statement stats, and summary |
| `export_camt.py` | Export parsed data to CSV and JSON files |
| `export_camt_excel.py` | Export to an Excel workbook (`.xlsx`) |
| `stream_camt.py` | Stream transactions incrementally with optional PII redaction |
| `parse_camt_zip.py` | Parse XML entries from a ZIP archive with hardened validation |

## PAIN.001 (ISO 20022 Payment Files)

| Script | Use case |
|---|---|
| `parse_pain001_basic.py` | Parse a PAIN.001 file and print payment records |
| `export_pain001.py` | Export payments to CSV and JSON |
| `stream_pain001.py` | Stream payments incrementally with PII redaction |

## Multi-Format

| Script | Use case |
|---|---|
| `parse_detected_formats.py` | Auto-detect and parse CSV, OFX, MT940, and CAMT files |
| `validate_input.py` | Validate file paths with `InputValidator` before parsing |
| `compatibility_wrappers.py` | Legacy API wrappers (`Camt053Parser`, `Pain001Parser`) |
| `cli_examples.sh` | CLI commands for CAMT and PAIN.001 parsing and export |

## ZIP Security

The `parse_camt_zip.py` example uses `iter_secure_xml_entries()` with hardened validation:

- **Max entry size:** 10 MB per XML member
- **Max total size:** 20 MB uncompressed
- **Max compression ratio:** 100:1
- **Encrypted entries:** Rejected

This matches the same validation the library exposes for production use.
