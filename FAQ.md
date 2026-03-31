# Frequently Asked Questions

## Data Privacy & Compliance

### Q: Does any data leave my infrastructure?

No. Bank Statement Parser runs entirely on your local machine. No API calls, no cloud services, no telemetry. XML parsers are hardened with `no_network=True`, which blocks all outbound network access at the parser level. Your financial data never leaves your environment.

### Q: How does PII redaction work for ISO 20022 files?

The parser identifies sensitive fields — debtor names (`<Dbtr/Nm>`), creditor names (`<Cdtr/Nm>`), IBANs, and postal addresses — and replaces them with `***REDACTED***` in console output and streaming mode. Redaction is **on by default**. File exports (CSV, JSON, Excel) retain unredacted data for downstream processing. Opt in to see full data with `--show-pii` on the CLI or `redact_pii=False` in the API.

### Q: Is the extraction process deterministic?

Yes. Given the same input file, the parser produces byte-identical output every time. No randomness, no model inference, no heuristic sampling. This is critical for financial auditing — run the same file twice and diff the output to verify. CI enforces this with 442 deterministic tests at 100% branch coverage.

### Q: What compliance standards does the project follow?

The repository maintains ISO 13485-aligned documentation: a quantified [Risk Register](docs/compliance/RISK_REGISTER.md) with severity/probability scoring, a [Verification & Validation Plan](docs/compliance/SOFTWARE_VALIDATION_PROCEDURE.md) with 19 gated steps, a [Change Control Procedure](docs/compliance/CHANGE_CONTROL_PROCEDURE.md), a [SOUP Register](docs/compliance/SOUP_REGISTER.md) covering all 17 dependencies, and a [Traceability Matrix](docs/compliance/TRACEABILITY_MATRIX.md) mapping 14 design inputs to implementation and verification. Every release includes a CycloneDX SBOM and SHA-256 checksums with GitHub build provenance attestation.

## Technical Specs & Performance

### Q: How are large files and ZIP archives handled?

Use `parse_streaming()` to process large XML files incrementally. Each transaction is yielded as a dictionary without loading the full document into memory. Elements are cleared after processing to prevent memory growth.

For ZIP archives, `iter_secure_xml_entries()` validates each member before extraction: entry size cap (default 10 MB), total uncompressed size cap (default 50 MB), compression ratio limit (default 100:1), and encrypted entry rejection. No file is written to disk — XML bytes are passed directly to `CamtParser.from_bytes()`.

### Q: Can I map custom CSV column headers to the standard schema?

Yes. `CsvStatementParser` normalizes column headers automatically. It recognizes common variations — `"Date"`, `"Transaction Date"`, `"Booking Date"` all map to the `date` field. `"Amount"`, `"Value"`, `"Sum"` map to `amount`. If your bank uses split columns for credits and debits (e.g., `"Credit"` and `"Debit"`), the parser detects and combines them into a single signed amount. No manual configuration required.

### Q: What is the output format of the DataFrames?

All parsers return a pandas `DataFrame`. CAMT output includes columns: `Amount` (float), `Currency` (str), `DrCr` (str: `"CRDT"` or `"DBIT"`), `Debtor` (str), `Creditor` (str), `Reference` (str), `ValDt` (str: ISO date), `BookgDt` (str: ISO datetime), and `AccountId` (str). PAIN.001 output includes `PmtInfId`, `PmtMtd`, `InstdAmt`, `Currency`, `CdtrNm`, `EndToEndId`, and additional header fields. CSV, OFX, and MT940 parsers produce normalized columns: `date`, `description`, `amount`.

### Q: Does the parser handle bank-specific dialects of CAMT.053?

The parser strips XML namespaces before processing, which means it handles any CAMT.053 variant — `camt.053.001.02`, `camt.053.001.04`, or proprietary bank wrappers — without namespace-specific configuration. XPath queries target the element structure, not the namespace URI. If your bank wraps CAMT in a custom envelope, use `from_string()` or `from_bytes()` to feed the inner document directly.

## Treasury Workflows

### Q: How does the parser handle multi-currency statements?

Each transaction carries its own `Currency` field extracted from the XML `Ccy` attribute. Multi-currency statements are preserved as-is — no implicit conversion or aggregation across currencies. The `get_account_balances()` method returns opening and closing balances per account with their original currency codes. Cross-currency reconciliation is left to your downstream logic, where you control the exchange rate source.

### Q: Does the parser support both PAIN.001 and CAMT formats?

Yes. `Pain001Parser` handles ISO 20022 PAIN.001 credit transfer initiation files (outgoing payments). `CamtParser` handles CAMT.053 bank-to-customer statement files (incoming reporting). Both support streaming, PII redaction, and export to CSV, JSON, and Excel. Use `detect_statement_format()` to identify the format automatically, or instantiate the parser directly when you know the type.

### Q: What happens when a transaction entry is malformed?

For batch parsing (`parse()`), malformed entries missing required fields (`Amount`, `Currency`, or `CdtDbtInd`) are skipped with a warning log. The rest of the statement parses normally. For streaming mode (`parse_streaming()`), parse errors propagate immediately as exceptions — no silent data loss. This fail-fast behavior is intentional for financial workflows where every transaction must be accounted for.
