# Verification & Validation Plan

**Document ID:** BSP-VVP-001
**Revision:** 2.0
**Effective date:** 2026-03-31
**Owner:** Quality Architect

---

## Purpose

Defines the deterministic verification and validation path for `bankstatementparser`. Every release artifact traces back to signed source code, verified dependencies, and automated test evidence.

---

## Scope

Covers all modules in the `bankstatementparser` package, supporting scripts under `scripts/`, CI/CD workflows, and third-party dependencies declared in `pyproject.toml`.

---

## Preconditions

| # | Condition | Enforcement |
|---|---|---|
| 1 | Signed commit on a protected branch or release tag | `commit-signature-verification.yml` |
| 2 | Clean `poetry.lock` with SHA-256 hashes for every file entry | `scripts/verify_locked_hashes.py` |
| 3 | Reproducible CI runner image with pinned workflow actions (SHA-locked) | `quality-gates.yml`, `security.yml` |
| 4 | All open P0 risk items resolved (Risk Register score < 15) | Manual gate |

---

## Validation Steps

### Phase 1 — Source Integrity

| Step | Action | Tool | Pass Criterion |
|---|---|---|---|
| V-01 | Verify commit signatures | `commit-signature-verification.yml` | Every commit in range has `verified: true` via GitHub API |
| V-02 | Install dependencies from lock file | `poetry install` | Exit code 0; no resolution changes |
| V-03 | Verify lock file hash coverage | `scripts/verify_locked_hashes.py` | All packages have `sha256:` entries for every file |

### Phase 2 — Static Analysis

| Step | Action | Tool | Pass Criterion |
|---|---|---|---|
| V-04 | Lint source code | Ruff | 0 errors |
| V-05 | Type-check source code | mypy (strict mode) | 0 errors |
| V-06 | Security static analysis | Bandit | 0 high/medium findings in production code |
| V-07 | Semantic vulnerability analysis | CodeQL | 0 alerts |
| V-08 | Secret detection | Gitleaks | 0 findings outside allowlisted test data |

### Phase 3 — Dynamic Verification

| Step | Action | Tool | Pass Criterion |
|---|---|---|---|
| V-09 | Unit and integration tests | pytest | Coverage gate met (no regression vs. base), 0 failures, 0 skipped |
| V-10 | Property-based fuzz testing | Hypothesis | All properties hold across generated examples |
| V-11 | Platform parity | GitHub Actions matrix | Tests pass on Ubuntu, macOS, and Windows |
| V-12 | Dependency vulnerability scan | pip-audit | 0 known CVEs in runtime dependencies |

### Phase 4 — Build & Provenance

| Step | Action | Tool | Pass Criterion |
|---|---|---|---|
| V-13 | Generate SBOM | `scripts/generate_sbom.py` | CycloneDX 1.5 JSON matches lock file |
| V-14 | Build wheel and sdist | `poetry build` | Both artifacts produced without error |
| V-15 | Generate artifact checksums | `scripts/generate_checksums.py` | `SHA256SUMS` file covers all artifacts in `dist/` |
| V-16 | Attest build provenance | `release-integrity.yml` | GitHub attestation linked to build artifacts |

### Phase 5 — Release Approval

| Step | Action | Owner | Pass Criterion |
|---|---|---|---|
| V-17 | Review test evidence, SBOM, and risk register | Release Approver | All V-01 through V-16 pass; no unresolved P0 items |
| V-18 | Archive validation record | Release Approver | Evidence bundle stored per retention policy |
| V-19 | Approve release | Release Approver | Signed tag applied to release commit |

---

## Acceptance Criteria

All of the following must be true before a release is approved:

- **V-01–V-16** pass on Linux, macOS, and Windows.
- **Every** commit in scope is signed and GitHub-verified.
- **Every** build artifact has a SHA-256 checksum.
- **SBOM** matches the lock file used for the build.
- **Risk Register** contains no items with residual score >= 15.
- **No** unresolved high-severity security findings.

---

## Evidence Retention

| Artifact | Retention | Storage |
|---|---|---|
| CI run logs | 90 days | GitHub Actions |
| Test coverage reports (`coverage.xml`) | Per release | GitHub Artifacts + repository |
| SBOM (`sbom.cyclonedx.json`) | Per release | GitHub Artifacts + `dist/` |
| Checksum manifest (`SHA256SUMS`) | Per release | GitHub Artifacts + `dist/` |
| Build attestation | Indefinite | GitHub Attestation API |
| Signed Git tags | Indefinite | Git repository |

---

## Review History

| Date | Revision | Changes |
|---|---|---|
| 2026-03-31 | 2.0 | Formalized as V&V Plan. Added phased structure, pass criteria per step, evidence retention, and release approval gate. |
