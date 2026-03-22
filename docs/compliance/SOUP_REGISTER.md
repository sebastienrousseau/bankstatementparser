# SOUP Register

## Scope

Software of Unknown Pedigree used by `bankstatementparser`.

| Component | Version Source | Purpose | License | Risk Notes | Verification |
| --- | --- | --- | --- | --- | --- |
| Python | CI/toolchain | Runtime | PSF | Interpreter behavior affects parsing and security controls | CI matrix |
| lxml | `poetry.lock` | XML parsing | BSD-like | XML parser misuse can create parser abuse risk | tests, Bandit, CodeQL |
| pandas | `poetry.lock` | DataFrame export and analysis | BSD-3-Clause | Data export and serialization surface | tests |
| openpyxl | `poetry.lock` | XLSX export | MIT | Output artifact integrity and macro handling concerns | tests |
| defusedxml | `poetry.lock` | Safe XML helpers | PSF | Security-critical parsing dependency | tests, review |

## Review Rules

- Every new third-party dependency requires a documented purpose.
- Every dependency change requires vulnerability review and SBOM refresh.
- Every security-sensitive dependency requires regression coverage.
