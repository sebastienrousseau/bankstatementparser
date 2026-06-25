# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- New `examples/hybrid/07_scan_and_ingest.py` example demonstrating
  `scan_and_ingest()` over a directory of statements: cross-file
  `transaction_hash` deduplication, the `ScanResult` summary, and the
  cross-statement `verify_continuity()` integrity check.
- `examples/hybrid/04_golden_rule.py` now also demonstrates
  `verify_transactions()` (currency-aware Golden Rule) and
  `verify_continuity()` (cross-statement chaining) alongside
  `verify_balance()`.
- `[tool.interrogate]` configuration enforcing **100% docstring
  coverage** across the package, the helper `scripts/`, and the
  runnable `examples/` (private and nested helpers included).
- `tests/test_regression_examples.py::test_every_example_script_is_exercised`
  asserts that every runnable script on disk is exercised by the
  regression suite, so no example can be added without coverage.

### Changed

- Documentation-coverage audit: added docstrings to every previously
  undocumented function, method, class, and nested helper (115 symbols
  across the package, scripts, and examples) to reach 100% interrogate
  coverage repo-wide.
- Coverage-integrity audit: removed 27 of 29 `# pragma: no cover`
  pragmas (and the unused `raise NotImplementedError` coverage
  exclusion) by making the guarded behaviour genuinely testable and
  adding the corresponding tests — covering the `/ingest` REST
  endpoint, the API server entrypoint, the `pdfplumber` engine path,
  the optional-dependency `ImportError` guards, the parallel
  worker-crash path, and the `_coerce_transactions` fallbacks. The two
  remaining pragmas are a provably-unreachable JSON guard and the
  standard `if __name__ == "__main__"` entrypoint.
- New `VerificationStatus.UNVERIFIABLE` member for statements that
  **cannot** be checked (missing opening/closing balance, fewer than
  two statements for a continuity check, or multi-currency balances
  that cannot be attributed to one currency). It sits between
  `DISCREPANCY` and `FAILED` in the aggregate worst-first precedence:
  `DISCREPANCY` > `FAILED` > `UNVERIFIABLE` > `VERIFIED`.

### Changed

- **Behavior change.** The "cannot apply the rule" cases that
  previously reported `FAILED` now report `UNVERIFIABLE`:
  `verify_balance`/`verify_transactions` with a missing
  opening/closing balance, `verify_balance_multi_currency` with no (or
  partial) per-currency balances, and `verify_continuity` with fewer
  than two statements or a missing balance on a link. `FAILED` is now
  reserved for a genuine verification error — no current code path
  emits it. **Migration:** code that matched `status == FAILED` for
  the missing-balance / cannot-verify case must now match
  `status == UNVERIFIABLE`.
- Review mode (`--type review`) now also routes `UNVERIFIABLE`
  statements to human review, not only `DISCREPANCY`/`FAILED` — a
  statement we could not verify should still be reviewed.
- Reworded the hybrid orchestrator's deterministic-detection warning.
  Instead of the misleading "Format detection failed: ..." (which read
  like an error for every PDF), it now emits a clear routing message —
  "No deterministic statement format matched (not XML/CSV/OFX/QFX/
  MT940); routing to the hybrid LLM/vision extraction pipeline" — and
  demotes the raw detector detail to `DEBUG` logging.

## [0.0.9] — 2026-06-11

> "Audit pass" — addresses the three Critical findings and all eight
> quick wins from the deep audit, adds a hybrid trust & correctness
> slice and an examples/docs regression suite, drains all open
> Dependabot version-bump PRs, resolves all open Dependabot security
> alerts, and removes the remaining silent-failure paths from the
> public API. The silent-failure fixes below are breaking changes
> and are flagged under **Changed — BREAKING** with migration notes;
> per [SemVer](https://semver.org) anything may change while the
> version is 0.y.z, and from 1.0.0 breaking changes will require a
> major release.

### Added (hybrid trust & quick wins)

- **Page provenance for text-LLM rows (`Transaction.source_page`).**
  `extract_text_pages()` keeps per-page text instead of joining the
  PDF into one blob, and `smart_ingest` attributes each extracted
  row back to the page whose text contains its description. Vision
  rows inherit the page from their bounding box. Untraceable rows
  keep `source_page=None`; the ingest CSV gains a `source_page`
  column and review mode prints it.
- **Cross-statement continuity check (`verify_continuity()`).** The
  closing balance of statement N must equal the opening balance of
  N+1 — a missing month, duplicated export, or hallucinated balance
  shows up as a `ContinuityBreak`. `scan_and_ingest` runs the check
  across scanned files in sorted order and exposes the
  `ScanResult.continuity` result.
- **French and Spanish CSV header synonyms.** `Date opération`,
  `Libellé`, `Montant`, `Solde`, `Devise`, `Fecha`, `Concepto`,
  `Importe`, `Saldo`, `Divisa`, and friends now map onto the
  deterministic CSV path. Header normalization folds accents
  (NFKD), so `Débit`/`Crédit`/`Référence` resolve via the existing
  English synonyms.
- **LLM-extraction accuracy eval harness.** New pure scoring module
  (`bankstatementparser.hybrid.evaluation`) compares an extraction
  against ground-truth cases (`tests/test_data/eval/`) and produces
  deterministic precision/recall/F1 plus per-field accuracies. The
  runner (`scripts/run_llm_eval.py`) supports `--mock` for a
  model-free harness self-check; CI runs the self-check as a
  blocking step and the real-model eval as a non-blocking job gated
  on the `BSP_EVAL_MODEL` repository variable.
- **`--review-below THRESHOLD` for `--type review`.** Per-row
  extraction confidence is now acted on, not just displayed: rows
  with `confidence` below the threshold (0.0–1.0) are routed into
  the interactive review walk even when statement-level
  verification passed. Statement-level `DISCREPANCY`/`FAILED`
  still reviews every row.
- **`verify_transactions()` and `aggregate_verifications()`**
  exported from `bankstatementparser.hybrid` — currency-aware
  Golden Rule dispatch and per-currency result aggregation.
- **Examples & docs regression suite.** Every shipped example
  script (`examples/`, `examples/hybrid/`, shell walkthroughs) is
  now executed end-to-end as a subprocess in CI
  (`tests/test_regression_examples.py`), and every fenced code
  block in README.md, FAQ.md, docs/index.md, and docs/MAPPING.md
  is either executed against the repository fixtures or has its
  imports verified (`tests/test_regression_docs.py`). New doc
  blocks must be classified in the suite or the build fails, and
  every CLI flag mentioned in the docs must exist on the parser.

### Fixed (hybrid trust)

- **Vision-extracted rows are labelled `source_method="vision"`.**
  Previously rows produced by the vision path were mislabelled
  `"llm"`, so per-row provenance disagreed with the
  `IngestResult.source_method` tag. `SourceMethod` now includes
  the `"vision"` literal.
- **Review mode re-runs the Golden Rule after edits.** The saved
  verification verdict previously stayed stale after rows were
  edited or deleted; the kept rows are now re-verified and a
  `reverify` entry (with before/after status) is appended to the
  audit trail.
- **Multi-currency statements no longer report a false
  `DISCREPANCY`.** `smart_ingest` previously summed all currencies
  into one Golden Rule check; transactions spanning multiple
  currencies are now verified per currency
  (`verify_balance_multi_currency`) and collapsed into a single
  statement-level verdict.
- **`--type camt` console output crashed on real statements.** The
  CLI converted `get_statement_stats()` (a DataFrame) with
  `list(...)`, yielding column names instead of rows — the display
  path then crashed in PII redaction (`'int' object has no
  attribute 'lower'`) and the `--output` path wrote column names
  as the CSV body. Caught by the new examples regression suite.

### Changed — BREAKING

- **`Pain001Parser.get_summary()` raises instead of returning an
  error dict.** Internal failures now raise `Pain001ParseError`
  (previously a summary full of `"Unknown"` values with an `"error"`
  key). The `error` key has been removed from `SummaryRecord`.
  *Migration:* wrap calls in
  `try: ... except Pain001ParseError:` instead of checking
  `"error" in summary`.
- **CAMT streaming no longer defaults transaction currency to
  `""`.** When an entry's `<Amt>` has no `Ccy` attribute, the
  statement-level account currency (`<Acct><Ccy>`) is used; if
  neither is present, `ParserError` is raised.
  *Migration:* files without any currency information now fail fast
  — previously they produced rows with an empty `Currency` that
  corrupted downstream aggregation.
- **`openpyxl` is now an optional extra.** Excel export
  (`CamtParser.camt_to_excel`) requires
  `pip install 'bankstatementparser[excel]'`; calling it without
  openpyxl raises `ImportError` with that hint.
  *Migration:* add the `excel` extra if you export to `.xlsx`.
- **lxml floor raised to `>=5.0`** (was `>=4.9.3`).

### Fixed (0.0.9)

- **CAMT streaming `AccountId` was always empty.** The account id
  was captured when `</Stmt>` closed — after every `<Ntry>` in the
  statement had already been yielded. It is now captured when
  `</Acct>` closes, so streamed rows carry the correct account id,
  matching the non-streaming path.
- **`ValidationError` moved to `bankstatementparser.exceptions`**
  alongside the rest of the hierarchy; it is still re-exported from
  `bankstatementparser.input_validator`, so existing imports keep
  working.
- **Parallel parsing preserves the failure type.**
  `FileResult.error` is now `"ExceptionType: message"` instead of
  the bare message.
- **Temp-file cleanup failures are logged** (`logger.debug`) in
  PAIN.001 streaming instead of silently swallowed.

### Added

- **Golden-file behavior corpus** — `tests/test_data/golden/` pins
  the exact parsed output (Decimal amounts, currencies, per-account
  balances, net amounts, strict-failure behavior) for realistic
  statement shapes: multi-currency CAMT, namespace-less CAMT,
  genuine same-day duplicates, garbled amounts, and
  German-formatted CSV. Enforced by `tests/test_golden_files.py`.
- **German CSV header recognition** — `CsvStatementParser` now maps
  `Buchungstag`, `Verwendungszweck`, `Betrag`, `Soll`, and `Haben`
  to the canonical date/description/amount/debit/credit columns,
  matching what `docs/MAPPING.md` already promised.
- **`CamtParser(..., allow_recovery=True)`** — opt-in recovery-mode
  reparse for malformed XML. Strict parsing is now the default (see
  Security below); recovery logs a warning because it can silently
  drop malformed content.

### Fixed

- **Decimal end-to-end, no silent `0.0`** — every monetary amount
  produced by the parsers (CAMT, PAIN.001, CSV, OFX/QFX, MT940) and
  carried through DataFrames and summaries is `decimal.Decimal`.
  Garbled amounts (e.g. `12..34`) and missing `<Amt>` elements now
  raise `ValueError`/`ValidationError` instead of silently becoming
  `0.0`.
- **Deduplication correctness** — `Transaction.transaction_hash`
  now includes `transaction_id or reference`, so distinct same-day
  transactions with bank-assigned IDs never collide.
  `dedupe_by_hash` uses occurrence-counted keys, making
  re-ingestion idempotent while genuine same-day repeats (two
  identical coffees) survive within a batch. `scan_and_ingest`
  deduplicates file-by-file so cross-file overlaps are still
  caught.
- **Index-space bug in `Deduplicator.deduplicate()`** — suspected-
  match exclusion previously trusted the caller-controlled
  `source_index`; it now uses the internal enumeration index, so
  custom `source_index` values can no longer exclude the wrong
  rows.

- **`value_date` no longer silently copies `booking_date`** in the
  LLM-backed extractor (`hybrid/llm_extractor.py`). LLM payloads that
  omit `value_date` now produce `Transaction.value_date is None`
  instead of an incorrect duplicate of `booking_date`. The text and
  vision prompts have been extended to allow an optional
  `value_date: "YYYY-MM-DD"|null` field for future model responses.
- **CAMT `parse_streaming` is now fail-fast on per-row errors**
  (`camt_parser.py`). Previously the streaming loop logged a warning
  and `continue`'d, silently dropping malformed transactions and
  contradicting the R-007 control in
  `docs/compliance/RISK_REGISTER.md`. Behaviour now matches the
  equivalent PAIN.001 streaming path and the documented control.

### Security

- **18 Dependabot security alerts closed** (#39–#56). Critical: litellm
  SQL injection in proxy API key verification (1.81.16–1.83.6) →
  bumped to 1.88.1. High: urllib3 cross-origin header leak (2.6.x) +
  decompression-bomb bypass → 2.7.0; lxml `iterparse` / `ETCompatXMLParser`
  default-config XXE → 6.1.1; litellm sandbox escape (1.81.8–1.83.9),
  authenticated command exec, SSTI in `/prompts/test` → 1.88.1.
  Medium: starlette host-header validation → 1.2.1; aiohttp cross-origin
  cookie + untrusted-data deserialization (<3.14.0) → 3.14.1; idna
  `idna.encode()` bypass (<3.15) → 3.18; pypdf FlateDecode RAM-exhaust
  + long-runtime paths (<6.10.2) → 6.13.2; python-dotenv symlink
  follow in `set_key` (<1.2.2) → 1.2.2; pytest tmpdir vulnerability
  (<9.0.3) → 9.0.3.
- **`litellm` is now Python-version-restricted to `<3.14`** in
  `pyproject.toml`. All security-patched litellm versions (≥1.83.10)
  declare `python <3.14,>=3.10` upstream, so this restriction is
  honest disclosure rather than a new limitation. The deterministic
  core remains supported on Python 3.10–3.14; the optional
  `[hybrid]`, `[hybrid-plus]`, `[hybrid-vision]`, and `[enrichment]`
  extras now require Python 3.10–3.13 (matching upstream litellm).
  Previously the lockfile silently held two litellm versions and
  installed the vulnerable 1.83.7 on Python 3.12+.
- **REST API safety floor** (`api.py`). Uploads are streamed in
  chunks; the request is rejected with HTTP 413 once the cumulative
  size exceeds `BSP_API_MAX_UPLOAD_BYTES` (default 25 MB). The
  caller-supplied filename is reduced to its basename and the suffix
  must match `InputValidator.ALLOWED_INPUT_EXTENSIONS` (HTTP 400
  otherwise). On parse failure the response carries a UUID
  `correlation_id`; the raw exception is logged server-side only
  (HTTP 422) to avoid leaking filesystem paths. Authentication,
  authorization, and rate limiting remain out of scope — see README
  for the documented deployment posture.
- **CAMT recovery-mode parsing is opt-in** — `CamtParser` rejects
  malformed XML (including entity-amplification payloads such as
  billion-laughs) at parse time by default; `recover=True` reparse
  only happens with an explicit `allow_recovery=True` and logs a
  warning. `SECURITY.md` gains an "XML Parsing: Why lxml" section
  documenting the hardened parser settings and their mitigations.

### Deprecated

- **`bank_statement_parsers.Pain001Parser` and `Camt053Parser`**
  compatibility wrappers now emit `DeprecationWarning`; use
  `pain001_parser.Pain001Parser` and `camt_parser.CamtParser`
  directly.

### Removed

- **`setup.py`** — stale legacy metadata mirror declaring
  `version="0.0.4"` (vs. the real `0.0.8`). Modern pip reads
  `pyproject.toml` directly; `setup.cfg` is retained for the same
  reason but kept in lock-step.
- **`tests/integration/test_euxis_dispatch*.py`** (4 files,
  ~2,500 LOC) and `tests/integration/test_manifests/`. These tested
  a `MockEuxisDispatcher` defined inside the test file with no
  corresponding production code in the package. `DI-14` in the
  traceability matrix has been removed.

### Changed

- **Dependency bumps** — closes the 20 open Dependabot PRs (#53–#78
  except #57 superseded). Notable: **pytest 8.4.2 → 9.0.3** (constraint
  widened to `>=8.0.0,<10.0.0` in `pyproject.toml`), **lxml 6.0.2 →
  6.1.1**, **numpy 1.26.x → 2.4.6** (via pandas), **pydantic-core
  2.41.5 → 2.46.4**, **hypothesis 6.151.10 → 6.155.2**, **ruff 0.15.9
  → 0.15.16**, **mypy 1.19.1 → 1.20.2**, **pypdf 6.10.0 → 6.13.2**,
  **pypdfium2 5.6.0 → 5.9.0**, **litellm 1.83.4 → 1.83.7+**, **starlette
  1.0.0 → 1.2.1**, **idna 3.11 → 3.18**, **urllib3 2.6.3 → 2.7.0**.
  GitHub Actions SHA pins refreshed for `actions/checkout`,
  `github/codeql-action`, `gitleaks/gitleaks-action`,
  `actions/dependency-review-action`, and `actions/upload-artifact`.
  Lockfile hash verification (`scripts/verify_locked_hashes.py`)
  passes against all 113 packages; `requirements.txt` regenerated
  from `poetry.lock`.
- **Apache 2.0 license header** added to
  `bankstatementparser/additional_parsers.py` (license hygiene).
- **`make clean`** now also removes `coverage.xml`, `.coverage`,
  `htmlcov/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`,
  `.hypothesis/`, `.benchmarks/`, and stale `__pycache__/`
  directories.
- **CI test selection** is no longer an enumerated list of files
  (`.github/workflows/quality-gates.yml`). The unit-tests job now
  runs `pytest tests/ --ignore=…` so newly added test files are
  picked up automatically. `tests/integration/test_zip_security.py`
  remains in the coverage run because it exercises
  `bankstatementparser.zip_security` directly.
- **LLM response parsing consolidated** — the duplicated
  markdown-fence stripping / JSON extraction / transaction
  coercion logic in `LLMExtractor` and `VisionExtractor` now lives
  in one module, `bankstatementparser/_llm_common.py`.
- **CLI internals deduplicated** — `parse_camt` and `parse_pain`
  delegate to a single shared implementation
  (`BankStatementCLI._parse_statement_file`); behaviour and the
  public method names are unchanged.
- **Honest coverage gate** — coverage is gated at 100%, reached
  with behavioural tests rather than line-arrow chasing: every
  remaining gap got a test that asserts observable behaviour, and
  the one genuinely unreachable defensive branch carries an
  explicit, justified `# pragma: no cover`. Codecov `target: auto`
  additionally fails any PR that regresses coverage against its
  base commit. `tests/test_branch_coverage.py` was rewritten as
  behaviour-framed `tests/test_parser_edge_behavior.py`, and
  `tests/test_coverage_gaps.py` renamed to
  `tests/test_error_paths.py` with behavioural docstrings replacing
  line-number references.

## [0.0.8] — 2026-04-11

> "Full Platform" — closes every gap identified in the competitive
> analysis. Multi-currency balance verification, hledger/beancount
> export, bulk directory scanner, account mapping rules, and a REST
> API microservice.

### Added

- **Multi-currency balance verification** —
  `verify_balance_multi_currency()` groups by currency and runs
  an independent Golden Rule check per group.
- **hledger + beancount export** — `to_hledger()` and
  `to_beancount()` in `bankstatementparser.export`.
- **Bulk directory scanner** — `scan_and_ingest()` scans a folder
  tree, runs smart_ingest on every match, deduplicates across the
  batch.
- **Account mapping rules** — `AccountMapper` with regex rules
  loaded from JSON config.
- **REST API** — FastAPI wrapper with `/ingest` and `/health`
  endpoints. `[api]` extra.

### Changed

- Version bumped `0.0.7` → `0.0.8`.

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

> "Intelligence Layer" — the full v0.0.6 milestone. Drops Python
> 3.9 to retire the entire transitive CVE allow-list inherited from
> v0.0.5, adds a categorization enrichment module, an interactive
> review mode for discrepancy resolution, and per-row bounding-box
> extraction from the vision pipeline. Closes
> [#44](https://github.com/sebastienrousseau/bankstatementparser/issues/44),
> [#45](https://github.com/sebastienrousseau/bankstatementparser/issues/45),
> [#46](https://github.com/sebastienrousseau/bankstatementparser/issues/46),
> [#47](https://github.com/sebastienrousseau/bankstatementparser/issues/47).

### Added

#### `bankstatementparser.enrichment` subpackage (#44)

- **`Categorizer`** — LiteLLM-backed transaction categorizer with
  pluggable schema. Default taxonomy is Plaid's 13-category set.
  Supports batch processing, graceful failure (no data loss on LLM
  errors), and schema-normalizing category label matching.
- **`EnrichedTransaction`** — wrapper (not mutator) around
  `Transaction` carrying `category`, `is_business_expense`,
  `enrichment_confidence`, and `rationale`. The original
  `Transaction` is never modified so dedup keys and audit trails
  stay stable.
- **`DEFAULT_CATEGORY_SCHEMA`** — Plaid's 13-category taxonomy as
  a tuple. Users with Xero, IRS Schedule C, or custom taxonomies
  pass their own tuple.
- **`[enrichment]`** install extra (litellm only).

#### Interactive review mode (#45)

- **`IngestResult.to_json()` / `.from_json()`** — stable JSON
  round-trip with `schema_version=1`, Decimal amounts as strings
  (no float drift), ISO-formatted dates, and an embedded
  `audit_trail` array that persists across review sessions.
- **`--type review` CLI subcommand** — reads a saved IngestResult
  JSON, walks every transaction with a single-character action
  menu (`a`ccept / `e`dit / `s`kip / `d`elete / `q`uit), records
  every operator action in the audit trail, and writes the updated
  result back to disk. Non-interactive (plain stdin/stdout) so it
  works on any terminal and is easy to mock in tests.
- **`.json`** added to `InputValidator.ALLOWED_INPUT_EXTENSIONS`
  and `ALLOWED_OUTPUT_EXTENSIONS`.

#### Per-row bounding-box extraction (#46)

- **`BoundingBox`** Pydantic model with normalized (0.0–1.0)
  coordinates and `page_index`, exported from the top-level
  package.
- **`Transaction.source_bbox: Optional[BoundingBox]`** — populated
  by the vision path when the multimodal model returns spatial
  coordinates. Always `None` for the deterministic and text-LLM
  paths.
- **`VISION_SYSTEM_PROMPT`** updated to ask the model for per-row
  bounding boxes in the JSON schema.
- **`_parse_bbox()`** helper in `llm_extractor.py` validates and
  converts the LLM-supplied bbox dict into a `BoundingBox`,
  rejecting malformed or out-of-range coordinates.

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

[Unreleased]: https://github.com/sebastienrousseau/bankstatementparser/compare/v0.0.9...HEAD
[0.0.9]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.9
[0.0.8]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.8
[0.0.7]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.7
[0.0.6]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.6
[0.0.5]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.5
[0.0.4]: https://github.com/sebastienrousseau/bankstatementparser/releases/tag/v0.0.4
