# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.7] — 2026-04-08

> "Universal Vision" — turns the local vision path from 🔴 to 🟢
> in the cross-platform matrix. Three independent improvements
> stacked on top of v0.0.6: a built-in direct Ollama bridge that
> sidesteps the upstream LiteLLM long-prompt hang, a switch from
> `llava` to `minicpm-v` as the recommended local vision model,
> and a new `strip_rows=True` mode that splits dense pages into
> overlapping bands so small local models can keep up.

### Added

#### `bankstatementparser.hybrid.ollama_direct` (new module)

- **`ollama_direct_completion(**kwargs)`** — drop-in replacement
  for `litellm.completion` that targets Ollama's `/api/chat`
  endpoint via `httpx`. Accepts the same OpenAI-style messages
  shape that `LLMExtractor` and `VisionExtractor` already build,
  returns an OpenAI-style response envelope so the existing
  JSON-parsing helpers work unchanged.
- **`is_ollama_model(model)`** — small helper used for
  auto-selection.
- **`OllamaDirectError`** — narrow error type so callers can
  distinguish bridge failures from upstream LLM failures.
- **Auto-selection** in both `VisionExtractor` and `LLMExtractor`:
  when `model.startswith("ollama/")` and no explicit
  `completion_fn` is passed, the extractor uses
  `ollama_direct_completion` automatically. **Zero user action
  required** — existing v0.0.5 / v0.0.6 vision code that hung at
  600 s now completes in ~33 s.

#### `VisionExtractor.strip_rows` mode

- New `strip_rows: bool = False` and `n_strips: int = 4`
  parameters on `VisionExtractor`. When enabled, each PDF page is
  rendered as `n_strips` overlapping horizontal strips
  (`STRIP_OVERLAP_FRACTION = 0.10`) and one LLM call runs per
  strip. Strip 0 (top) gets a "header" prompt that asks for
  `account_id`, `currency`, and balances; subsequent strips get a
  "body" prompt that asks for transactions only. Results are
  merged via `Transaction.transaction_hash` so rows that bisect
  a strip boundary are dedup'd automatically.
- Designed for **dense pages** (≥ 15 rows) where small local
  models can't process the full page in one call because their
  CLIP vision encoder downscales any input to 336×336 internally,
  destroying fine table detail. Trades a few extra LLM calls for
  substantially better per-row accuracy.

### Changed

- **Recommended local vision model** is now `ollama/minicpm-v`
  (5.5 GB), not `ollama/llava` (4.7 GB). minicpm-v is explicitly
  trained for OCR and document understanding tasks; llava was a
  general-purpose multimodal model that pre-dated the
  document-specific fine-tunes that arrived in 2025. Smoke-test
  comparison on the synthetic scanned PDF:

  | Model | Result |
  |---|---|
  | `ollama/llava:7b` | Hallucinated INR currency, fabricated "Cash Withdrawal" rows |
  | `ollama/minicpm-v:8b` | All 11 transactions extracted, GBP, correct balances |

- All examples, FAQ entries, and documentation that referenced
  `ollama/llava` now reference `ollama/minicpm-v` first, with
  llava kept as a comparison data point in the smoke-test results
  table.
- Version bumped `0.0.6` → `0.0.7`.

### Smoke-test results (real Ollama models, Apple Silicon, 2026-04-08)

| Path | Model | Mode | Result |
|---|---|---|---|
| Text-LLM | `ollama/llama3` | single-shot | ✅ All 11 rows, `confidence=1.00`, **VERIFIED**, ~25 s |
| Vision-LLM | `ollama/minicpm-v:8b` | single-shot | ✅ All 11 rows, currency `GBP`, balances correct, **~33 s**. Two sign-flip errors fixable via strip mode. |
| Vision-LLM | `ollama/minicpm-v:8b` | strip_rows=True | ✅ Sign convention correct, ~43 s (4 LLM calls). Year confabulation on body strips when only printed in header band. |

### Migration notes

The public API is **fully backwards compatible**. Existing v0.0.5 /
v0.0.6 code that constructs `VisionExtractor(model="ollama/llava")`
keeps working — it just runs ~33 s faster instead of hanging. To
opt into the new defaults, change the env var:

```diff
- export BSP_HYBRID_VISION_MODEL=ollama/llava
+ export BSP_HYBRID_VISION_MODEL=ollama/minicpm-v
```

To use the new strip mode for dense pages:

```python
from bankstatementparser.hybrid import VisionExtractor, smart_ingest

vision = VisionExtractor(strip_rows=True, n_strips=4)
result = smart_ingest("dense_statement.pdf", vision_extractor=vision)
```

If you need to keep using LiteLLM (e.g. for an Ollama model
configured behind a LiteLLM proxy), pass an explicit
`completion_fn=litellm.completion` to `VisionExtractor` to opt
out of the auto-selected bridge.

## [0.0.6] — 2026-04-08

> "Intelligence Layer (kickoff)" — first release in the v0.0.6
> milestone. Drops Python 3.9 to retire the entire transitive CVE
> allow-list inherited from v0.0.5 and unblock cleaner dependency
> resolution for the rest of the milestone (categorization, review
> mode, OCR bbox mapping). Closes
> [#47](https://github.com/sebastienrousseau/bankstatementparser/issues/47).

### Removed

- **Python 3.9 support.** Python 3.9 reached end-of-life on
  2025-10-31. The minimum supported interpreter is now Python 3.10.
  Users on Python 3.9 must stay on v0.0.5 or upgrade their
  interpreter. This is a **breaking change** for the Python
  classifiers and `python_requires` metadata; the public API is
  unchanged.
- The 6-row CI matrix is now 5 rows (3.10 → 3.14) for both
  `lint-and-typecheck` and `unit-tests` jobs.

### Security

- **Deleted the entire transitive CVE allow-list** from
  `.github/workflows/security.yml`. All nine GHSAs allow-listed in
  v0.0.5 are now resolved by upgrading to the patched series of
  every transitive dependency:

  | Package | v0.0.5 | v0.0.6 | Advisories closed |
  |---|---|---|---|
  | `litellm` | 1.80.0 | 1.83.4 | GHSA-jjhc-v7c2-5hh6, GHSA-53mr-6c8q-9789, GHSA-69x8-hrgq-fjj8 |
  | `cryptography` | 43.0.3 | 46.0.7 | GHSA-r6ph-v2qm-q3c2, GHSA-79v4-65xg-pq4g, GHSA-m959-cc7f-wv43 |
  | `pillow` | 11.3.0 | 12.2.0 | GHSA-cfh3-3jmp-rvhc |
  | `filelock` | 3.19.1 | 3.25.2 | GHSA-w853-jp5j-5j7f, GHSA-qmgc-5h2g-mvrw |
  | `requests` | 2.32.5 | 2.33.1 | GHSA-gc5v-m9x4-r6x2 |

  The `dependency-review-action` step in CI is now back to its
  bare default — no per-CVE bypasses, no documented justifications,
  no "revisit when minimum Python is raised" reminders.
- `litellm` minimum bumped from `>=1.50.0` to `>=1.83.0` in
  `pyproject.toml` so the patched series is enforced at install
  time, not just in the lockfile.

### Changed

- `pyproject.toml`:
  - `[tool.poetry.dependencies] python` from `>=3.9` to
    `>=3.10,<4.0` (the upper bound is required by Poetry's
    resolver for the new litellm constraint)
  - `[tool.black] target-version` from `py39` to `py310`
  - `[tool.ruff] target-version` from `py39` to `py310`
  - `[tool.mypy] python_version` from `3.9` to `3.10`
  - Version bumped `0.0.5` → `0.0.6`
- `setup.cfg` and `setup.py` (legacy parallel metadata): same
  Python floor bumps and classifier list updated (3.9 row removed).
- `[tool.ruff] lint.ignore` extended to include `UP007` alongside
  the existing `UP045`. Both rules want PEP 604 syntax (`X | None`
  instead of `Optional[X]`); migrating ~100 occurrences across the
  package is deliberately deferred to a follow-up cleanup PR so
  this release stays focused on the Python 3.9 retirement.

### Fixed

- `bankstatementparser/camt_parser.py`: pre-existing `zip(...)`
  call now passes `strict=False` explicitly. Resolves the new
  ruff `B905` warning that surfaces under `target-version = py310`
  (the rule was inactive under py39).
- `bankstatementparser/hybrid/llm_extractor.py` and
  `bankstatementparser/hybrid/vision.py`: `Callable` is now
  imported from `collections.abc` instead of `typing`. Resolves
  the new ruff `UP035` warning.

### Migration notes

The public API is **unchanged**. v0.0.5 user code runs on v0.0.6
without modification provided the interpreter is Python 3.10 or
newer. If you are still on Python 3.9, pin to v0.0.5 in your
`requirements.txt` / `pyproject.toml` until you are able to
upgrade.

```text
# requirements.txt — pin if you cannot upgrade Python yet
bankstatementparser==0.0.5
```

## [0.0.5] — 2026-04-08

> "Universal Extraction" — combines the deterministic reliability of
> the existing ISO/exchange-format parsers with an adaptive LLM layer
> for unstandardized PDFs, including a multimodal vision fallback for
> scanned/image-only statements. The core "data only, no inference"
> philosophy of the library is preserved: categorization and review-
> mode UI are intentionally deferred to v0.0.6.

### Added

#### Hybrid pipeline (`bankstatementparser.hybrid`)

- **`smart_ingest()`** — single entry point that routes any file
  through the cheapest viable extraction path:
  - **Path A — Deterministic** for ISO/exchange formats ($0)
  - **Path B — Text-LLM** for digital PDFs (≥ 50 chars extractable)
  - **Path C — Vision-LLM** for scanned PDFs (auto-routed via
    `LOW_TEXT_DENSITY_THRESHOLD`)
- **`LLMExtractor`** — LiteLLM-backed text extractor with
  provider-agnostic configuration via `BSP_HYBRID_MODEL`. Default
  model is `ollama/llama3` (local, private). Tolerant JSON parsing
  handles markdown fences and prose wrappers.
- **`VisionExtractor`** — multimodal extractor for scanned/image-only
  PDFs. Renders pages with `pypdfium2` (pure-Python wheel, no
  poppler dependency) and sends base64 PNGs via LiteLLM's multimodal
  payload. Vision model is opt-in only via `BSP_HYBRID_VISION_MODEL`.
- **`verify_balance()`** — Golden Rule integrity check returning
  `VERIFIED | DISCREPANCY | FAILED` with the exact delta when
  mismatched.
- **`extract_text()`** — `pypdf` by default, `pdfplumber` via
  `[hybrid-plus]` for difficult table layouts.
- **Structured prompts** — explicitly instruct the model to sort
  transactions chronologically, mitigating PDF reading-order issues.

#### `Transaction` model upgrades

- **`transaction_hash`** — computed field (MD5 of
  `date | normalized_description | amount`). Every row carries an
  immutable fingerprint for idempotent re-ingestion.
- **`source_method`** — `Literal["deterministic", "llm"]`, audit
  provenance per row.
- **`confidence`** — `Optional[float]`, populated for LLM rows.
- **`category`** and **`raw_source_text`** — reserved placeholders
  for the v0.0.6 "Intelligence Layer" release. No current logic;
  future-proofed to avoid a breaking schema migration.

#### `normalize_description()` noise stripping

- Strips inline dates (`2026-04-01`, `01/04`), times (`12:49`), and
  long alphanumeric IDs so that recurring charges hash identically.
  `AMZN MKTPLACE 2026-04-01 #A1B2C3` and `AMZN MKTPLACE 2026-04-02
  #Z9Y8X7` collapse to the same normalized form, which means
  `dedupe_by_hash()` actually catches real duplicates instead of
  being defeated by one rotating reference character.

#### `Deduplicator.dedupe_by_hash()`

- New strict identity filter using `Transaction.transaction_hash`,
  designed for incremental ingestion (syncing to Google Sheets, a
  database, etc.). Mutates a caller-owned `seen_hashes: set[str]`
  so consumers can persist state across batches. Coexists with the
  existing fuzzy/temporal `deduplicate()` method.

#### CLI

- New `--type ingest` subcommand that routes through `smart_ingest()`
  and prints source method, transaction table, verification status,
  and warnings. Graceful degradation when the `[hybrid]` extra is
  missing — catches `ImportError` both at top level and lazily
  inside `smart_ingest`, surfaces the specific missing dependency
  name, and prints a `pip install` hint.
- New `bankstatementparser` console-script entry point. Both forms
  work in parallel: `bankstatementparser --type ingest --input ...`
  and `python -m bankstatementparser.cli --type ingest --input ...`.
- `.pdf` added to `InputValidator.ALLOWED_INPUT_EXTENSIONS`.

#### Packaging — three new install extras

| Extra | Adds | When to use |
|---|---|---|
| `[hybrid]` | `litellm`, `pypdf` | digital PDFs (Path B) |
| `[hybrid-plus]` | + `pdfplumber` | tricky table layouts |
| `[hybrid-vision]` | + `pypdfium2` | scanned/image PDFs (Path C) |

Core install stays lean — none of the above are required for the
existing deterministic parsers.

#### Examples — `examples/hybrid/`

- Eight new files including a Mermaid flow diagram, prerequisites
  table, 15-minute quick start, mock-vs-live mode comparison,
  cross-platform verification matrix, and troubleshooting table.
- `generate_sample_pdfs.py` produces reproducible synthetic UK-bank
  PDFs (digital + scanned) so the LLM examples are runnable without
  real bank PDFs.
- `01_smart_ingest_deterministic.py` through `06_cli_walkthrough.sh`
  cover every code path. Each LLM example runs in two modes — MOCK
  (default, fully offline, CI-safe) and LIVE (set `BSP_HYBRID_MODEL`
  / `BSP_HYBRID_VISION_MODEL`).
- All examples verified end-to-end on real local Ollama models on
  Apple Silicon. Smoke-test results documented in
  `examples/hybrid/README.md`.

### Changed

- All copyright headers updated from `Copyright (C) 2023 Sebastien
  Rousseau.` to `Copyright (C) 2023-2026 Bank Statement Parser. All
  rights reserved.` across 24 source files.
- Test count grew from 484 to 541 (100% line and branch coverage
  retained, including the new hybrid subpackage).
- `Deduplicator` deprecation: none. The existing fuzzy/temporal
  `deduplicate()` API is unchanged; `dedupe_by_hash()` is purely
  additive.
- README rewritten to highlight the hybrid pipeline as a
  first-class feature alongside the deterministic parsers.

### Fixed

- `_coerce_transactions` in the orchestrator now catches the
  specific exceptions `Transaction.from_record` can raise
  (`ValueError`, `TypeError`, `KeyError`, `DecimalException`,
  `ValidationError`) and logs skipped rows at DEBUG level instead
  of swallowing all exceptions silently. Resolves Bandit B112.

### Security

- Allow-listed nine transitive CVEs across `litellm` (3),
  `cryptography` (3), `pillow` (1), `filelock` (2), and `requests`
  (1) in `.github/workflows/security.yml`. All nine share the same
  root cause: their patched versions require Python ≥ 3.10, while
  this release still supports Python 3.9. Each advisory is
  documented per-CVE with the reason its vulnerable code path is
  unreachable from anything we ship (LiteLLM proxy server, X.509
  cert validation, PSD decoder, TOCTOU local races, requests
  path-extraction helper). The entire allow-list can be deleted in
  a single commit when the minimum Python is raised.
- New mypy overrides for `litellm`, `pypdf`, `pdfplumber`, and
  `pypdfium2`.

### Documentation

- New `examples/hybrid/README.md` with three-path Mermaid diagram,
  prerequisites table per install slice, 15-minute quick start,
  cross-platform verification matrix (macOS / Linux / WSL / native
  Windows), and troubleshooting table including the verified
  upstream LiteLLM ↔ Ollama vision-prompt hang.
- Top-level `README.md` updated with hybrid pipeline section,
  three new install variants, console-script usage, and updated
  Examples table.
- This `CHANGELOG.md` file (new).

### Smoke-test results (real Ollama models, Apple Silicon, 2026-04-08)

| Path | Model | Result |
|---|---|---|
| A — Deterministic | n/a | ✅ CAMT.053 fixture, 3 transactions, all hashes computed |
| B — Text-LLM | `ollama/llama3` (4.7 GB) | ✅ All 11 transactions extracted with `confidence=1.00`, balance VERIFIED, ~25s end-to-end |
| C — Vision-LLM | `ollama/llava:7b` (4.7 GB) | ⚠️ Library code verified correct, but blocked by reproducible upstream LiteLLM ↔ Ollama hang on long system prompts. Direct Ollama call works in 18s but llava-7b hallucinates statement contents at any render scale. Recommended production path: hosted vision models (`gpt-4o`, `claude-opus-4-6`, `gemini-2.5-pro`). |
| Golden Rule | n/a | ✅ All three outcomes (`VERIFIED`, `DISCREPANCY`, `FAILED`) reproduce as documented |
| Dedupe | n/a | ✅ Recurring Amazon dup caught in batch 1, both already-seen rows caught in batch 2 |
| CLI `--type ingest` | n/a | ✅ Deterministic path produces expected DataFrame with all v0.0.5 columns |

### Deferred to v0.0.6

- **Categorization** (`category` field populated, `is_business_expense`
  flag) — adding LLM-inferred classifications changes the library's
  trust model. Will ship as an opt-in `bankstatementparser.enrichment`
  module.
- **Interactive review mode** — will ship as a separate
  `--type review` subcommand consuming saved `IngestResult` JSON,
  keeping automated pipelines automated.
- **OCR chunk-to-row mapping** — true bounding-box mapping from the
  vision path, paired with review mode in v0.0.6.
- **Drop Python 3.9 support** — Python 3.9 reached EOL on
  2025-10-31. Bumping to `>= 3.10` lets the entire transitive-CVE
  allow-list be deleted in a single commit.

## [0.0.4] — Earlier release

See the git history for changes prior to v0.0.5. The CHANGELOG was
introduced in v0.0.5; earlier releases are not back-filled.

[Unreleased]: https://github.com/sebastienrousseau/bankstatementparser/compare/v0.0.7...HEAD
[0.0.7]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.7
[0.0.6]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.6
[0.0.5]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.5
[0.0.4]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.4
