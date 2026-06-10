# Traceability Matrix

**Document ID:** BSP-TM-001
**Revision:** 2.0
**Effective date:** 2026-03-31
**Owner:** Quality Architect

---

## Purpose

Maps every design input (user need) through implementation to verification evidence. Establishes bidirectional traceability per ISO 13485:2016 Section 7.3.

---

## Design Input → Implementation → Verification

| ID | Design Input (User Need) | Requirement | Implementation | Verification | Risk Ref |
|---|---|---|---|---|---|
| DI-01 | Parse ISO 20022 CAMT.053 bank statements from files | Accept `.xml` file path, return structured transaction data | `camt_parser.py` | `test_camt_parser.py`, `test_edge_cases.py` | R-001 |
| DI-02 | Parse CAMT.053 from in-memory XML | Accept XML string or bytes, return structured data without disk I/O | `camt_parser.py` (`from_string`, `from_bytes`) | `test_camt_parser.py`, `test_security_updated.py` | R-001 |
| DI-03 | Parse CAMT.053 from ZIP archives | Extract and parse XML members from ZIP without writing to disk | `zip_security.py`, `camt_parser.py` | `tests/integration/test_zip_security.py` | R-002 |
| DI-04 | Parse ISO 20022 PAIN.001 payment files | Accept `.xml` file path, return structured payment data | `pain001_parser.py` | `test_pain001_parser.py` | R-001 |
| DI-05 | Parse CSV, OFX, QFX, and MT940 formats | Auto-detect format and return structured data | `additional_parsers.py` | `test_additional_parsers.py` | — |
| DI-06 | Validate input files before parsing | Reject dangerous paths, oversized files, non-XML content, and binary payloads | `input_validator.py` | `test_input_validator.py`, `test_security_boundaries.py` | R-006 |
| DI-07 | Redact PII in output by default | Mask account numbers, names, and addresses unless explicitly opted in | `cli.py`, `camt_parser.py`, `pain001_parser.py` | `test_pii_redaction.py` | R-005 |
| DI-08 | Stream large files without exhausting memory | Incremental XML parsing with element cleanup | `camt_parser.py`, `pain001_parser.py` (`parse_streaming`) | `test_performance.py`, `test_coverage_gaps.py` | R-007 |
| DI-09 | Export to CSV, JSON, and Excel | Write parsed data to standard interchange formats | `base_parser.py`, `camt_parser.py` | `test_unified_interface.py`, `test_edge_cases.py` | — |
| DI-10 | Command-line interface | Parse statements via `python -m bankstatementparser.cli` | `cli.py` | `test_cli.py` | — |
| DI-11 | Enforce signed commits in CI | Block unverified commits from reaching `main` | `scripts/verify_github_commit_signatures.py` | `commit-signature-verification.yml` | R-004 |
| DI-12 | Generate SBOM for every release | Produce CycloneDX 1.5 JSON with all dependencies | `scripts/generate_sbom.py` | `release-integrity.yml`, `test_supply_chain_tools.py` | R-003 |
| DI-13 | Generate artifact checksums | Produce SHA-256 checksums for wheel and sdist | `scripts/generate_checksums.py` | `release-integrity.yml`, `test_supply_chain_tools.py` | R-003 |
| DI-14 | Deduplicate transactions across sources | Deterministic hashing for exact matches; configurable similarity for suspected matches | `transaction_deduplicator.py`, `transaction_models.py` | `test_transaction_deduplicator.py` | — |
| DI-15 | Optional Polars DataFrame export | Convert parsed output to Polars DataFrame or LazyFrame | `base_parser.py` (`to_polars`, `to_polars_lazy`) | `test_polars_export.py` | — |
| DI-16 | Parallel multi-file parsing | Process multiple statement files across CPU cores | `parallel.py` (`parse_files_parallel`) | `test_performance_contracts.py` | — |

---

## Coverage Summary

| Category | Count | Coverage |
|---|---|---|
| Design inputs | 16 | 100% mapped to implementation |
| Implementation modules | 13 | 100% mapped to verification |
| Risk linkages | 7 of 16 | Security-relevant inputs linked to Risk Register |
| Test coverage | 100% | Branch coverage enforced in CI |

---

## Review History

| Date | Revision | Changes |
|---|---|---|
| 2026-03-31 | 2.0 | Added design input IDs, user need descriptions, risk register cross-references, and coverage summary. Expanded from 9 to 14 traced requirements. |
| 2026-06-10 | 2.1 | Removed DI-14 (dispatch manifest validation) — out of scope for this library; renumbered subsequent rows. |
