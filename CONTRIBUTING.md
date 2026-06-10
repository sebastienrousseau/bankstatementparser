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
make install-hooks   # wires the pre-commit hook (runs `make verify` on every commit)
```

The pre-commit hook runs the full verification pipeline (ruff + mypy +
pytest + bandit, ~80 s on Apple Silicon) before every commit. This is
the same gate CI enforces — if the hook passes locally, CI will pass
on GitHub. To skip on a quick-iteration WIP commit:

```bash
git commit --no-verify -m "WIP: ..."   # NOT recommended for push-ready commits
```

### Optional extras for hybrid pipeline work

If you'll touch `bankstatementparser/hybrid/`, install the relevant extra:

```bash
# Text-LLM path (digital PDFs) — adds litellm + pypdf
poetry install --with dev -E hybrid

# Higher-fidelity table extraction — adds pdfplumber on top of [hybrid]
poetry install --with dev -E hybrid-plus

# Vision-LLM path (scanned/photocopied PDFs) — adds pypdfium2
poetry install --with dev -E hybrid-vision
```

All extras are pure-Python and opt-in. The full test suite runs without
any extra installed because the hybrid tests monkeypatch `litellm`,
`pypdf`, and `pypdfium2` via `sys.modules`. CI does not require the
extras to be present.

## Before Opening a Pull Request

Run the full validation suite. The Makefile groups the four gates under
a single target so they run in the same order CI does:

```bash
make verify
```

Or run them individually:

```bash
poetry run ruff check bankstatementparser tests examples scripts
poetry run mypy bankstatementparser
poetry run pytest --cov=bankstatementparser  # coverage gate is enforced
poetry run bandit -r bankstatementparser examples scripts -c pyproject.toml
```

All four commands must pass with zero errors. A minimum-coverage gate
(`--cov-fail-under` in `pyproject.toml`) is enforced silently — always
pass `--cov=bankstatementparser` so you see the missing-lines report
immediately.

## Signed Commits

Every commit must be signed. Configure Git once:

```bash
git config --global commit.gpgsign true
git config --global tag.gpgSign true
git config --global gpg.format ssh
git config --global user.signingkey "<your-signing-key>"
```

### Don't have a signing key yet? One-shot setup

```bash
# 1. Generate an Ed25519 SSH signing key (or reuse your existing one)
ssh-keygen -t ed25519 -C "you@example.com" -f ~/.ssh/id_signing

# 2. Wire it into git
git config --global commit.gpgsign true
git config --global tag.gpgSign true
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_signing.pub

# 3. Add the public half to GitHub as a Signing Key (not an Auth key)
gh ssh-key add ~/.ssh/id_signing.pub --type signing --title "$(hostname) signing"
```

The `gh ssh-key add` step is the one new contributors most often skip.
Without it, GitHub shows your commits as "Unverified" even though they
are cryptographically signed locally.

CI verifies signatures via the GitHub API. Unsigned commits block the
pipeline. The `main` branch has `required_signatures=true` enforced —
you cannot merge a PR whose tip commit is unsigned.

## Pull Request Rules

- **One branch, one purpose.** Keep the scope focused.
- **Describe the behavior change**, not the implementation.
- **Link the issue** when one exists.
- **Add tests** for parser, validation, or CLI changes.
- **Update examples or docs** when public behavior changes.

## Reporting Bugs

Open an issue with:

- **Input format** — one of: CAMT, PAIN.001, CSV, OFX, QFX, MT940, or PDF
- **For PDF inputs** (`--type ingest`): which extraction path was taken
  (`source_method` from the result — `deterministic`, `llm`, or `vision`),
  which model was used (`BSP_HYBRID_MODEL` / `BSP_HYBRID_VISION_MODEL`),
  and whether mock or live mode if running an example
- Expected behavior
- Actual behavior
- Minimal reproduction path
- Affected version or commit SHA

For security vulnerabilities, use [`.github/SECURITY.md`](.github/SECURITY.md). Do not open a public issue.
