# Contributing

Keep changes small. Keep behavior clear. Keep history signed.

## Local Setup

Clone and install on **macOS, Linux, or WSL**:

```bash
git clone https://github.com/sebastienrousseau/bankstatementparser.git
cd bankstatementparser
python3 -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install --with dev
```

## Before Opening a Pull Request

Run the full validation suite:

```bash
ruff check bankstatementparser tests examples scripts
python -m mypy bankstatementparser
python -m pytest
bandit -r bankstatementparser examples scripts -q
```

All four commands must pass with zero errors.

## Signed Commits

Every commit must be signed. Configure Git once:

```bash
git config --global commit.gpgsign true
git config --global tag.gpgSign true
git config --global gpg.format ssh
git config --global user.signingkey "<your-signing-key>"
```

CI verifies signatures via the GitHub API. Unsigned commits block the pipeline.

## Pull Request Rules

- **One branch, one purpose.** Keep the scope focused.
- **Describe the behavior change**, not the implementation.
- **Link the issue** when one exists.
- **Add tests** for parser, validation, or CLI changes.
- **Update examples or docs** when public behavior changes.

## Reporting Bugs

Open an issue with:

- Input format (CAMT, PAIN.001, CSV, OFX, MT940)
- Expected behavior
- Actual behavior
- Minimal reproduction path
- Affected version or commit SHA

For security vulnerabilities, use [SECURITY.md](.github/SECURITY.md). Do not open a public issue.
