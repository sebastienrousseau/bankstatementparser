# Traceability Matrix

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Parse CAMT from disk | `bankstatementparser/camt_parser.py` | `tests/test_camt_parser.py` |
| Parse CAMT from memory | `bankstatementparser/camt_parser.py` | `tests/test_camt_parser.py`, `tests/test_security_updated.py` |
| Secure ZIP ingestion | `bankstatementparser/zip_security.py` | `tests/integration/test_zip_security.py` |
| Parse PAIN.001 from disk | `bankstatementparser/pain001_parser.py` | `tests/test_pain001_parser.py` |
| Validate file and payload input | `bankstatementparser/input_validator.py` | `tests/test_input_validator.py` |
| PII redaction | parser and CLI flows | `tests/test_pii_redaction.py` |
| Signed commit enforcement in CI | `scripts/verify_github_commit_signatures.py` | `commit-signature-verification.yml` |
| SBOM generation | `scripts/generate_sbom.py` | `release-integrity.yml`, integration tests |
| Artifact checksum generation | `scripts/generate_checksums.py` | `release-integrity.yml`, integration tests |
