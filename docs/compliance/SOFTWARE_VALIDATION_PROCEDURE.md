# Software Validation Procedure

## Purpose

Defines the deterministic validation path for `bankstatementparser`.

## Preconditions

- Signed commit on a protected branch or release tag
- Clean dependency lock file with SHA-256 hashes
- Reproducible CI runner image and pinned workflow actions

## Validation Steps

1. Verify commit signatures with `.github/workflows/commit-signature-verification.yml`.
2. Install dependencies from `poetry.lock`.
3. Verify lockfile SHA-256 coverage with `scripts/verify_locked_hashes.py`.
4. Run static analysis:
   - Ruff
   - mypy
   - Bandit
   - CodeQL
   - Gitleaks
5. Run package and integration tests.
6. Generate SBOM with `scripts/generate_sbom.py`.
7. Build `sdist` and `wheel`.
8. Generate artifact checksums with `scripts/generate_checksums.py`.
9. Attest release provenance with `.github/workflows/release-integrity.yml`.
10. Archive:
    - test evidence
    - SBOM
    - checksum manifest
    - attestation
    - release approval record

## Acceptance Criteria

- All required checks pass on Linux, macOS, and Windows.
- All commits in scope are signed and verified by GitHub.
- All build artifacts have SHA-256 checksums.
- The SBOM matches the lock file used for the build.
- Security scans report no unresolved high-severity findings.
