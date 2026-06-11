# Risk Register

**Document ID:** BSP-RISK-001
**Revision:** 2.0
**Effective date:** 2026-03-31
**Owner:** Security Architect

---

## Risk Assessment Methodology

### Severity Scale

| Level | Label | Definition |
|---|---|---|
| 5 | **Catastrophic** | Data breach exposing PII, arbitrary code execution, complete loss of data integrity |
| 4 | **Critical** | Denial of service, unauthorized file access, silent data corruption |
| 3 | **Serious** | Partial data loss, degraded parsing accuracy, misleading financial output |
| 2 | **Minor** | Cosmetic output errors, non-critical performance degradation |
| 1 | **Negligible** | No user impact, internal logging anomaly |

### Probability Scale

| Level | Label | Definition |
|---|---|---|
| 5 | **Certain** | Occurs on every invocation with malicious input |
| 4 | **Likely** | Occurs with common attack patterns |
| 3 | **Possible** | Requires crafted input and specific conditions |
| 2 | **Unlikely** | Requires deep knowledge of internals |
| 1 | **Rare** | Theoretical; no known exploit path |

### Risk Score

**Risk = Severity x Probability.** Range: 1–25.

| Score | Classification | Action |
|---|---|---|
| 15–25 | **Unacceptable** | Block release until mitigated below threshold |
| 8–14 | **Tolerable** | Mitigate before next major release |
| 1–7 | **Acceptable** | Monitor; address opportunistically |

**Acceptance threshold:** All production risks must score **< 15** after controls.

---

## Identified Hazards

| ID | Hazard | Cause | Sev | Prob | Raw | Control | Residual Sev | Residual Prob | Residual | Verification |
|---|---|---|---|---|---|---|---|---|---|---|
| R-001 | Malicious XML payload execution (XXE, entity expansion) | Untrusted XML with DOCTYPE, external entities, or billion-laughs patterns | 5 | 4 | **20** | `defusedxml` + hardened `lxml.XMLParser` (`resolve_entities=False`, `no_network=True`, `load_dtd=False`, `huge_tree=False`) | 5 | 1 | **5** | `tests/test_security.py`, `tests/test_security_updated.py` |
| R-002 | ZIP decompression abuse (zip bomb, path traversal) | Oversized members, high compression ratio, encrypted entries | 4 | 3 | **12** | `zip_security.py`: entry size cap, total size cap, compression ratio limit, encrypted entry rejection | 4 | 1 | **4** | `tests/integration/test_zip_security.py` |
| R-003 | Dependency tampering or supply-chain compromise | Floating action refs, unsigned artifacts, unchecked hashes | 5 | 2 | **10** | Pinned GitHub Actions by SHA, `poetry.lock` SHA-256 hash verification, CycloneDX SBOM, build provenance attestation | 5 | 1 | **5** | `security.yml`, `release-integrity.yml`, `scripts/verify_locked_hashes.py` |
| R-004 | Unauthorized code introduction | Unsigned commits, bypassed review, compromised contributor | 5 | 2 | **10** | SSH-signed commits enforced in CI, branch protection, PR review requirement | 5 | 1 | **5** | `commit-signature-verification.yml`, GitHub branch rules |
| R-005 | Sensitive data exposure (PII leakage) | Raw XML fields containing names, IBANs, or addresses in logs or exports | 4 | 3 | **12** | Column-level PII redaction in parsers and CLI, `--show-pii` opt-in flag with warning, no PII in default log output | 4 | 1 | **4** | `tests/test_pii_redaction.py` |
| R-006 | Path traversal via crafted file paths | Symlinks, `../` sequences, environment variable injection in file paths | 4 | 3 | **12** | `InputValidator`: dangerous pattern blocklist, symlink resolution check, system directory blocklist | 4 | 1 | **4** | `tests/test_input_validator.py`, `tests/integration/test_security_boundaries.py` |
| R-007 | Silent financial data loss in streaming mode | Malformed XML element causes parser exception mid-stream | 3 | 2 | **6** | Streaming errors propagate immediately (fail-fast); no silent `continue` | 3 | 1 | **3** | `tests/test_error_paths.py`, `tests/test_enterprise_coverage.py` |

---

## Risk Review

| Review Date | Reviewer | Changes |
|---|---|---|
| 2026-03-31 | Security Architect | Initial quantified assessment. Added R-006, R-007. Assigned severity/probability to all hazards. |

**Next scheduled review:** Before each major release or within 90 days.
