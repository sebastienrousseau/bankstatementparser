# Frequently Asked Questions

## Data Privacy & Compliance

### 1. Does any data leave my infrastructure?

**No.** Bank Statement Parser operates as a stateless library. All processing — parsing, PII redaction, archive extraction — occurs within your local runtime memory. No API calls, no cloud services, no telemetry. XML parsers are hardened with `no_network=True`, blocking all outbound access at the parser level. Your financial data never leaves your environment.

### 2. How does PII redaction work for ISO 20022 files?

**Sensitive fields are masked before they reach your application logic.** The parser identifies debtor names (`<Dbtr/Nm>`), creditor names (`<Cdtr/Nm>`), IBANs, and postal addresses, replacing them with `***REDACTED***` in console output and streaming mode. Redaction is on by default. File exports (CSV, JSON, Excel) retain unredacted data for downstream processing. Opt in to full data with `--show-pii` on the CLI or `redact_pii=False` in the API.

### 3. Is the extraction process deterministic?

**Yes — byte-identical output on every run.** Given the same input file, the parser produces the same result every time. No randomness, no model inference, no heuristic sampling. Verify this yourself: run the same file twice and diff the output. CI enforces determinism with 442 tests at 100% branch coverage, including property-based fuzzing via Hypothesis.

### 4. What compliance standards does the project follow?

**ISO 13485-aligned documentation with full traceability.** The [SOUP Register](docs/compliance/SOUP_REGISTER.md) tracks all 22 dependencies (5 direct, 10 transitive, 1 optional, 6 toolchain). The repository maintains:

- A quantified [Risk Register](docs/compliance/RISK_REGISTER.md) with severity/probability scoring and residual risk assessment
- A [Verification & Validation Plan](docs/compliance/SOFTWARE_VALIDATION_PROCEDURE.md) with 19 gated steps across 5 phases
- A [Change Control Procedure](docs/compliance/CHANGE_CONTROL_PROCEDURE.md) with impact assessment and rollback protocols
- A [SOUP Register](docs/compliance/SOUP_REGISTER.md) covering all 17 dependencies with risk levels and EOL tracking
- A [Traceability Matrix](docs/compliance/TRACEABILITY_MATRIX.md) mapping 14 design inputs to implementation and verification

Every release includes a CycloneDX SBOM, SHA-256 checksums, and GitHub build provenance attestation.

## Technical Specs & Performance

### 5. How are large files and ZIP archives handled?

**Streaming with bounded memory — tested at 50,000 transactions per file.** Use `parse_streaming()` to process XML files incrementally. Each transaction is yielded as a dictionary; elements are cleared after processing to prevent memory growth. Memory does not scale with file size — the 50K-transaction test (25+ MB) uses less than 2x the memory of the 10K-transaction test.

Performance thresholds validated in CI:

- **CAMT:** >5,000 transactions/second at 10K and 50K scale
- **PAIN.001:** >2,000 transactions/second at 10K and 50K scale
- **Memory:** Growth ratio between 10K and 50K stays below 2x

For files exceeding 50 MB (e.g., host-to-host PAIN.001 batches with 100K+ payments), the parser streams through a temporary file with chunk-based namespace stripping — the full document is never loaded into memory.

For ZIP archives, `iter_secure_xml_entries()` validates each member before extraction:

- Entry size cap (default 10 MB)
- Total uncompressed size cap (default 50 MB)
- Compression ratio limit (default 100:1)
- Encrypted entry rejection

No file is written to disk. XML bytes pass directly to `CamtParser.from_bytes()`.

### 6. Can I map custom CSV column headers to the standard schema?

**Yes — automatic normalization, zero configuration.** `CsvStatementParser` recognizes common header variations: `"Date"`, `"Transaction Date"`, `"Booking Date"` all map to the `date` field. `"Amount"`, `"Value"`, `"Sum"` map to `amount`. Split credit/debit columns (e.g., `"Credit"` and `"Debit"`) are detected and combined into a single signed amount automatically.

### 7. What is the output format of the DataFrames?

**Standardized pandas DataFrames with consistent column types.**

| Format | Columns |
|---|---|
| **CAMT** | `Amount` (float), `Currency` (str), `DrCr` (`"CRDT"`/`"DBIT"`), `Debtor`, `Creditor`, `Reference`, `ValDt` (ISO date), `BookgDt` (ISO datetime), `AccountId` |
| **PAIN.001** | `PmtInfId`, `PmtMtd`, `InstdAmt`, `Currency`, `CdtrNm`, `EndToEndId`, plus header fields (`MsgId`, `CreDtTm`, `NbOfTxs`) |
| **CSV/OFX/MT940** | `date`, `description`, `amount` (normalized) |

### 8. Does the parser handle bank-specific dialects of CAMT.053?

**Yes — namespace-agnostic by design.** The parser strips XML namespaces before processing, handling any CAMT.053 variant (`camt.053.001.02`, `camt.053.001.04`, or proprietary bank wrappers) without namespace-specific configuration. XPath queries target element structure, not namespace URIs. For banks that wrap CAMT in a custom envelope, use `from_string()` or `from_bytes()` to feed the inner document directly.

## Treasury Workflows

### 9. How does the parser handle multi-currency statements?

**Each transaction preserves its original currency — no implicit conversion.** The `Currency` field is extracted from the XML `Ccy` attribute per transaction. Multi-currency statements remain as-is. The `get_account_balances()` method returns opening and closing balances per account with original currency codes. Cross-currency reconciliation is left to your downstream logic, where you control the exchange rate source.

### 10. Does the parser support both PAIN.001 and CAMT formats?

**Yes — outgoing payments and incoming reporting.** `Pain001Parser` handles ISO 20022 PAIN.001 credit transfer initiation files (outgoing payments). `CamtParser` handles CAMT.053 bank-to-customer statement files (incoming reporting). Both support streaming, PII redaction, and export to CSV, JSON, and Excel. Use `detect_statement_format()` to identify the format automatically, or instantiate the parser directly.

### 11. What happens when a transaction entry is malformed?

**Batch mode skips; streaming mode fails fast.**

- **`parse()`** — Malformed entries missing required fields (`Amount`, `Currency`, or `CdtDbtInd`) are skipped with a warning log. The rest of the statement parses normally.
- **`parse_streaming()`** — Parse errors propagate immediately as exceptions. No silent data loss. This fail-fast behavior is intentional for financial workflows where every transaction must be accounted for.

---

## Note on Determinism and Reproducibility

Bank Statement Parser is designed for environments where auditability is non-negotiable. The guarantees:

- **No network access.** `lxml.XMLParser` is configured with `resolve_entities=False`, `load_dtd=False`, and `no_network=True`. No external resource is ever fetched.
- **No floating state.** Parsers are stateless. Instantiate, parse, discard. No caching, no side effects between invocations.
- **Hash-verified dependencies.** Every package in `poetry.lock` has SHA-256 file hashes verified by `scripts/verify_locked_hashes.py`. The CycloneDX SBOM maps every runtime component.
- **Signed provenance.** Every commit is SSH-signed. Every release carries GitHub build provenance attestation linking the artifact to its source commit and build environment.

To verify reproducibility locally:

```bash
python -m pytest                              # 442 tests, 100% branch coverage
python scripts/verify_locked_hashes.py        # SHA-256 hash verification
git log --show-signature -1                   # Verify commit signature
```
