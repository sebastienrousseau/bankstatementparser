# Security Policy

## Supported Versions

| Version | Supported | Notes |
|---|---|---|
| 0.0.9 (current) | Yes | Requires Python ≥ 3.10 (LLM extras: ≤ 3.13) |
| 0.0.8 | Yes | Requires Python ≥ 3.10 |
| 0.0.7 | Yes | Requires Python ≥ 3.10 |
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

## XML Parsing: Why lxml

CAMT.053 and PAIN.001 files are parsed with **lxml** rather than
`defusedxml` because the parsers rely on lxml-specific features
(streaming via `iterparse`, full XPath). The known XML attack classes
are mitigated by constructing every `XMLParser` with hardened
settings instead:

| Setting | Mitigates |
|---|---|
| `resolve_entities=False` | XXE — external/internal entities are never expanded |
| `load_dtd=False` | DTD-based attacks (parameter entities, DTD retrieval) |
| `no_network=True` | SSRF via network-reachable DTDs or entities |
| `huge_tree=False` | Memory exhaustion from oversized documents (libxml2 hard limits apply) |
| `recover=False` (default) | Silent acceptance of malformed content; billion-laughs payloads are rejected at parse time by libxml2's entity-amplification limit |

Recovery-mode parsing (`recover=True`) is **opt-in** via
`CamtParser(..., allow_recovery=True)` and logs a warning when used,
because it can silently drop malformed content. Input size limits and
content validation are additionally enforced by
`bankstatementparser/input_validator.py` before any bytes reach lxml.
These properties are pinned by `tests/test_security.py` and
`tests/test_security_updated.py`.
