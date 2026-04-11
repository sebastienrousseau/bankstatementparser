# Security Policy

## Supported Versions

| Version | Supported | Notes |
|---|---|---|
| 0.0.7 (current) | Yes | Requires Python ≥ 3.10 |
| 0.0.6 | Yes | Requires Python ≥ 3.10 |
| 0.0.5 | Yes | Last release supporting Python 3.9 |
| < 0.0.5 | No | |

## Reporting a Vulnerability

Report security vulnerabilities via [GitHub Security Advisories](https://github.com/sebastienrousseau/bankstatementparser/security/advisories/new).

**Do not** open a public issue for security vulnerabilities.

### Include in Your Report

- **Type of issue** — XXE, path traversal, injection, denial of service, etc.
- **Affected file(s)** — Full path and line number.
- **Reproduction steps** — Minimal steps to trigger the vulnerability.
- **Proof of concept** — Code or payload demonstrating the issue (if available).
- **Impact assessment** — What an attacker gains: data access, code execution, denial of service.

### Response Timeline

| Milestone | Target |
|---|---|
| **Acknowledgment** | Within 48 hours |
| **Triage and severity classification** | Within 5 business days |
| **Fix or mitigation plan** | Within 15 business days for Critical/High severity |
| **Patch release** | Within 30 days of confirmed Critical/High finding |

### Severity Classification

| Severity | Definition |
|---|---|
| **Critical** | Remote code execution, data breach, authentication bypass |
| **High** | Denial of service, unauthorized file access, PII exposure |
| **Medium** | Information disclosure, input validation bypass |
| **Low** | Cosmetic, informational, defense-in-depth improvement |

### Disclosure Policy

- Coordinate disclosure with the maintainer before public release.
- Credit is given to reporters in the release notes (unless anonymity is requested).
- Fixes are released as patch versions with a corresponding GitHub Security Advisory.

## Security Controls

This project enforces the following automated security controls:

- **Signed commits** — Verified in CI via `commit-signature-verification.yml`
- **Static analysis** — Bandit SAST, CodeQL, Ruff
- **Secret scanning** — Gitleaks with `.gitleaks.toml` configuration
- **Dependency auditing** — pip-audit, lock file hash verification, CycloneDX SBOM
- **Build provenance** — GitHub attestation on every tagged release
