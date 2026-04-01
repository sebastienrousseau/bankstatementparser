# SOUP Register

**Document ID:** BSP-SOUP-001
**Revision:** 2.0
**Effective date:** 2026-03-31
**Owner:** Security Architect

---

## Purpose

Tracks all Software of Unknown Pedigree (third-party components not developed under this project's quality system). Each entry includes purpose, risk assessment, and verification method per ISO 13485:2016 Section 7.5.2.

---

## Runtime Dependencies (Direct)

| Component | Version | License | Purpose | Risk Level | Risk Notes | Verification | EOL / Support |
|---|---|---|---|---|---|---|---|
| **lxml** | 6.0.2 | BSD | XML parsing (CAMT, PAIN.001) | **High** | Core attack surface for XXE, entity expansion, malformed XML | Bandit, CodeQL, `test_security.py`, `test_security_updated.py` | Active; maintained by lxml.de |
| **pandas** | 2.3.3 | BSD-3-Clause | DataFrame construction and export | **Medium** | Data serialization surface; FutureWarning API drift | Unit tests, `test_edge_cases.py` | Active; major release cadence ~12 months |
| **openpyxl** | 3.1.5 | MIT | Excel (`.xlsx`) export | **Low** | Output artifact integrity | `test_edge_cases.py` (Excel export) | Active |
| **defusedxml** | 0.7.1 | PSF-2.0 | Safe XML parsing helpers | **Critical** | Security-critical — mitigates XXE and entity expansion | `test_security.py`, code review | Active; low change frequency |
| **pydantic** | 2.12.5 | MIT | Transaction models and deduplication data classes | **Medium** | Data validation and serialization; Rust-based core (pydantic-core) | `test_transaction_deduplicator.py`, `test_polars_export.py` | Active; major release cadence ~6 months |

## Runtime Dependencies (Transitive)

| Component | Version | License | Pulled By | Risk Level | Verification |
|---|---|---|---|---|---|
| **numpy** | 2.4.4 | BSD | pandas | Low | Transitively tested via pandas operations |
| **python-dateutil** | 2.9.0 | Apache/BSD | pandas | Low | Transitively tested |
| **pytz** | 2026.1 | MIT | pandas | Low | Transitively tested |
| **et-xmlfile** | 2.0.0 | MIT | openpyxl | Low | Transitively tested |
| **six** | 1.17.0 | MIT | python-dateutil | Low | Transitively tested |
| **pydantic-core** | 2.41.5 | MIT | pydantic | Low | Transitively tested |
| **annotated-types** | 0.7.0 | MIT | pydantic | Low | Transitively tested |
| **typing-inspection** | 0.4.2 | MIT | pydantic | Low | Transitively tested |
| **tzdata** | 2025.3 | Apache-2.0 | pandas | Low | Transitively tested |

## Optional Dependencies

| Component | Version | License | Purpose | Risk Level | Risk Notes | Verification | EOL / Support |
|---|---|---|---|---|---|---|---|
| **polars** | 1.32.0+ | MIT | Alternative DataFrame backend via `to_polars()` | **Low** | Optional; no security surface. Import guarded with `ImportError` fallback. | `test_polars_export.py` | Active; high release cadence |

## Toolchain (CI/Dev Only)

| Component | Version | License | Purpose | Verification |
|---|---|---|---|---|
| **Python** | 3.9–3.14 | PSF-2.0 | Runtime interpreter | CI matrix across 6 versions |
| **Poetry** | 2.3.2 | MIT | Build system, dependency resolution | Pinned in CI workflows |
| **pytest** | 8.4.2 | MIT | Test runner | Self-testing |
| **hypothesis** | 6.151.10 | MPL-2.0 | Property-based testing | Self-testing |
| **ruff** | 0.1.15 | MIT | Linter and formatter | CI gate |
| **mypy** | 1.19.1 | MIT | Static type checker | CI gate |
| **bandit** | 1.9.4 | Apache-2.0 | Security static analysis (SAST) | CI gate |
| **pygments** | 2.20.0 | BSD | Syntax highlighting (bandit transitive) | CVE-2026-4539 fixed at 2.20.0 |

---

## Review Rules

1. **New dependency** — Document purpose, license, risk level, and verification method in this register before merge.
2. **Version update** — Run `pip-audit`, refresh SBOM, verify lock file hashes. Update this register.
3. **Security-sensitive dependency** (risk level High or Critical) — Requires Security Architect review and regression test coverage.
4. **Quarterly review** — Scan all entries for EOL status, new CVEs, and license changes.

---

## Review History

| Date | Reviewer | Changes |
|---|---|---|
| 2026-03-31 | Security Architect | Expanded to include all transitive and toolchain deps. Added risk levels, EOL tracking, and review cadence. |
