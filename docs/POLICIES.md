# Policies

## Supported Python versions

`bankstatementparser` supports **Python 3.10 to 3.15**. The floor is
`pyproject.toml`'s `python = ">=3.10,<4.0"`, the same range the
package's classifiers declare, and the README's toolchain badge states
it.

| Python | Core install | `[hybrid]`, `[hybrid-vision]`, `[enrichment]` | `[hybrid-plus]` (pdfplumber) |
| :--- | :--- | :--- | :--- |
| 3.10 | Supported | Installs without `litellm` | Installs without `pdfplumber` |
| 3.11 | Supported | Supported | Supported |
| 3.12 | Supported | Supported | Supported |
| 3.13 | Supported | Supported | Supported |
| 3.14 | Supported | Installs without `litellm` | Supported |
| 3.15 | Supported, with pandas 3 | Installs without `litellm` | Supported |

Why the optional extras are narrower than the core:

- `litellm` currently requires Python below 3.14 upstream, and the
  first `filelock` release without open advisories (4.2.1) needs
  Python 3.11. The LLM extras therefore need Python 3.11 to 3.13.
- `pdfplumber` pulls Pillow, and the first Pillow without open
  advisories (13.0.0) dropped Python 3.10.
- pandas 2.3.3, the last 2.x release, has no Python 3.15 wheel, so on
  3.15 the core installs pandas 3 (3.0.6 or later) and numpy 2.5.2 or
  later. Python 3.10 to 3.14 keep pandas 2.

Deterministic parsing (CAMT, PAIN.001, MT940, MT942, BAI2, OFX, QFX,
CSV) works on every supported version.

### How support is enforced

Every pull request runs the full test suite, with its 100% coverage
gate, on Ubuntu, macOS and Windows for each of Python 3.10 to 3.15
(`.github/workflows/quality-gates.yml`), and lint and type checks on
each version. A version is supported when that matrix passes on it.

### Dropping a version

A Python version leaves the supported range only in a release whose
CHANGELOG says so, as Python 3.9 did in 0.0.6; 0.0.5 is the last
release that runs on 3.9. The floor in `pyproject.toml`, the CI
matrix, this page and the README badge change together in that
release.

## Versioning

The project follows Semantic Versioning. While the version is `0.y.z`,
any release may contain breaking changes; each is listed under a
**Changed — BREAKING** heading in the CHANGELOG with migration notes.
Deprecations emit `DeprecationWarning` for at least one minor release
before removal. The whole suite (core, loaders, writers, transport,
MCP and LSP servers, and the website) releases in lockstep under one
version number.

## Security fixes

Supported releases and the disclosure process are in
[`SECURITY.md`](https://github.com/sebastienrousseau/bankstatementparser/blob/main/SECURITY.md).
