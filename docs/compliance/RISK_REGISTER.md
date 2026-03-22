# Risk Register

| ID | Hazard | Cause | Control | Verification |
| --- | --- | --- | --- | --- |
| R-001 | Malicious XML payload execution | Entity expansion, DTD, external entity access | Hardened XML parser configuration and validation | parser tests, security tests |
| R-002 | ZIP decompression abuse | Oversized members, ratio abuse, encrypted entries | `zip_security.py` checks and threat tests | `tests/integration/test_zip_security.py` |
| R-003 | Dependency tampering | Floating action refs, unsigned artifacts, unchecked hashes | pinned actions, checksum generation, provenance attestation | CI workflows |
| R-004 | Unauthorized code introduction | Unsigned commits or bypassed review | signed-commit verification, CODEOWNERS, branch protection policy | GitHub settings + CI |
| R-005 | Sensitive data exposure | Raw XML or PII in logs or exports | redaction, limited logging, secure examples | PII tests, review |
