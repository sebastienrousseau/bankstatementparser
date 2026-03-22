# Contributing

Keep changes small. Keep behavior clear. Keep history signed.

## Requirements

- Use a signed commit for every change.
- Open a pull request against `main`.
- Add or update tests for every behavior change.
- Keep documentation aligned with the code.

## Local Setup

### macOS

```bash
git clone https://github.com/sebastienrousseau/bankstatementparser.git
cd bankstatementparser
python3 -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install --with dev
```

### Linux

```bash
git clone https://github.com/sebastienrousseau/bankstatementparser.git
cd bankstatementparser
python3 -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install --with dev
```

### WSL

```bash
git clone https://github.com/sebastienrousseau/bankstatementparser.git
cd bankstatementparser
python3 -m venv .venv
source .venv/bin/activate
pip install poetry
poetry install --with dev
```

## Run Before Opening a Pull Request

```bash
ruff check bankstatementparser tests examples scripts
python -m mypy bankstatementparser
python -m pytest
bandit -r bankstatementparser examples scripts -q
```

## Signed Commits

Configure Git to sign every commit:

```bash
git config --global commit.gpgsign true
git config --global tag.gpgSign true
git config --global gpg.format ssh
git config --global user.signingkey "<signing-key>"
```

The repository also verifies signed commits in CI.

## Pull Request Rules

- Use a focused branch.
- Describe the behavior change clearly.
- Link the relevant issue when one exists.
- Include tests for parser, validation, or CLI changes.
- Update examples or docs when public behavior changes.

## Reporting Bugs

Open an issue with:

- the input format
- the expected behavior
- the actual behavior
- a minimal reproduction path
- the affected version or commit

For security issues, use [VULNERABILITY_REPORTING.md](VULNERABILITY_REPORTING.md).
