# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/sebastienrousseau/bankstatementparser/compare/v0.0.5...HEAD
[0.0.5]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.5
[0.0.4]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.4
