<!-- SPDX-License-Identifier: Apache-2.0 OR MIT -->

# September 2026 audit remediation

Work belongs to `feat/v0.0.20`. The original assessment is retained separately
as `~/Downloads/BSP.md`. It is a baseline, not a claim that remediation has
finished. This document tracks the first implementation batch and the remaining
work. The assessment date is September 2026; references to 2027 describe a
planning horizon, not observations from the future.

## First implementation batch

| Finding | Implemented | Remaining acceptance work |
| --- | --- | --- |
| F01 CAMT namespaces | XML element names handle default namespaces, either quote style, and prefixes | Broader bank dialect corpus |
| F02 CAMT eager/streaming divergence | Both public paths share transaction expansion; nested `TxAmt` supported; ambiguous or nonconserving batches fail | FX instructed/booked amount policy |
| F03 MT940 dates | Adapter emits ISO dates before model coercion; model rejects ambiguous six-digit dates | Bank-specific date-century policy and additional reversal fixtures |
| F04 OFX accounts | Transaction metadata scoped to each bank/card statement | Investment OFX and per-account summary API |
| F05 CSV precision | Read textual cells before Decimal conversion; preserve leading zeros; reject missing amount columns | Explicit dialect and date-format configuration |
| F06 transaction identity | Versioned account/currency-scoped hashes; distinct IDs excluded from fuzzy matching; description included in primary key | Occurrence-aware identity when bank IDs are missing and persisted-state migration tooling |
| F07 reconciliation | Indexed candidate lookup; require currency/direction compatibility; exact references; explicit fee tolerance; reject ambiguous candidates and conflicting dates/accounts; per-currency settled volumes | Broader settlement corpus; many-to-one settlements |
| F08 analytics | Recognize parser field aliases; reject invalid amounts; retain Decimal precision; unknown currency is explicit; recurrence isolates accounts/directions and requires distinct dates | Average daily balance and calendar-aware projections |
| F09 API installation | Declare multipart dependency, resolve real FastAPI annotations, report package version; real API/Parquet CI covers Python 3.10, 3.12 and 3.14 | Enforce isolated installed-wheel tests in CI |
| F10 API resources | Clean temporary files; ingest outside event loop; bound pre-multipart body size, admissions and receive time; retain cancelled workers until completion | Isolate/time-limit ingestion workers and provider calls |
| F11 PDF forensics | Invalid/uninspected documents no longer imply authenticity; clean inspection means `NO_INDICATORS` | Calibrated risk scoring, signature verification and real-document corpus |
| F12 privacy | CAMT opt-in redaction covers parties, identifiers and narratives; CLI displays use common sensitive-field vocabulary; PAIN eager/streaming/summary/CSV and compatibility-wrapper parity | End-to-end export/provenance policy |
| F13 hybrid completeness | Reject over-budget PDFs; route mixed text/scanned files to vision; close native render resources; map crop coordinates to original pages; merge adjacent crop observations using identity and spatial evidence while preserving multiplicity | Worker/provider budgets; automatic balance verification; real PDF/model accuracy corpus |
| F14 Parquet types | Preserve Arrow Decimal/date/timestamp types; fail unsupported columns explicitly | Explicit canonical schema and bounded streaming writer |
| F15 SBOM validity | UUID serial numbers, textual marker properties, retain dependency references to all locked variants | Full schema validation in CI and marker-aware deployment-specific graphs |

## Performance and engineering follow-up

- Make XML parser construction lazy and streaming memory independent of file
  size. Measure constructor-to-first-record latency and process RSS, including
  allocations made before iteration.
- Replace per-row CLI DataFrames with a stable-schema CSV writer. Bound parallel
  futures and results, avoid redundant reads, and distinguish eager from lazy
  dataframe adapters.
- Maintain separate performance baselines for correctness fixes. Direct CAMT
  element traversal avoids repeated XPath compilation in the shared reader.
- Add real bank-format and PDF ground truth, differential tests, and measured
  model accuracy. Synthetic/mock evaluation alone is not an accuracy claim.
- Continue repository-standard work in separate commits: canonical README,
  developer and architecture guides, ADRs, contributor/governance templates,
  typed-package marker, documentation checks, and release preflight/readback.
- The branch now contains a blocking `Required Quality Gates` aggregate, real
  API/Parquet integration job, feature-branch documentation builds, and advisory
  scanning for all extras. Making these required on protected `main` is a
  separate repository-settings action; a workflow file alone does not enforce
  branch protection.
- Release artifacts, packaging submissions, signed release tags, public release
  notes and remote readback require the eventual release workflow. Existing
  published tags must not be rewritten during remediation.

## Compatibility

See [migration notes](MIGRATION-v0.0.20.md) before deploying this branch. Do not
mix old and new persisted transaction hashes. Financial behavior corrections
change output and matching even though most call signatures remain compatible.

## Local validation of this batch

- `make verify`: 1,003 passed, five skipped, five slow tests deselected;
  100% line/branch coverage; Ruff, mypy and Bandit passed (Python 3.12.14).
- `poetry run pytest --no-cov -m slow tests/test_performance_contracts.py -q`:
  all five performance contracts passed.
- `poetry run mkdocs build --strict`: passed.
- `poetry run interrogate bankstatementparser scripts examples`: 100% documented.
- Generated SBOM validated against the official CycloneDX 1.5 JSON schema with
  zero errors locally; full schema validation is not yet an enforced CI gate.
- `pip-audit` over the Poetry export including all extras and development
  dependencies: no known vulnerabilities on the audit date.
- Hashed requirements export matches the checked-in file; `poetry check --lock`
  passed with existing Poetry metadata-deprecation warnings. Published companion
  package versions agree with the current `0.0.19` manifest.

These are local results. The workflow changes provide future CI enforcement;
branch protection and release acceptance remain separate from these results.


## Second implementation batch

The first commit's remote quality matrix exposed CAMT throughput below the
existing 5,000 transactions/second threshold on several covered test runners.
The parser now expands entries directly without allocating/copying a synthetic
statement tree per entry. Namespace handling avoids repeated QName work for
unnamespaced elements, and direct attribute access replaces hot XPath queries.
The performance thresholds and coverage requirement remain unchanged.

A three-run local comparison on 10,000 generated transactions measured median
streaming throughput of approximately 9,600 before and 14,500 after the change.
This is a local throughput comparison, not an end-to-end memory or latency
claim; eager construction remains in the follow-up list.

PDF changes reject page-budget overflow before rendering or calling a model,
route an entire mixed PDF to vision when any page has sparse text, and close
PDF, page, bitmap, PIL, and crop resources on success and failure. Crop metadata
maps bounding boxes back to the correct page. Overlap merging requires matching
identity and at least 80% bounding-box intersection-over-union in adjacent
strips, consuming one previous observation per match. Repeated rows on the same
strip or different pages and rows without spatial evidence remain distinct.
Model-provided boxes are evidence, not proof; calibrated real-bank validation
and provider deadlines remain outstanding.

Second-batch local validation: `make verify` passed 1,016 tests with 100%
line/branch coverage; all five slow performance contracts, strict MkDocs,
and 100% documentation coverage passed. A native PDFium smoke check rendered
a two-page PDF in both modes and rejected an over-budget document in both modes.
Remote quality, security, documentation and signature checks passed for commit
`5356990`, including the unchanged throughput gate across the quality matrix.


## Third implementation batch

Recurrence keys include account identity and signed amounts. Bank direction takes
precedence over raw amount sign, using the same interpretation as cash-flow
summaries. Distinct dates establish cadence while preserving row multiplicity.
Unknown accounts remain a separate group; zero amounts do not establish patterns.

API admission starts before multipart decoding. A disk-backed spool validates
actual body bytes, including chunked uploads and false Content-Length headers.
The body budget includes 64 KiB above the file cap for multipart overhead.
Default admission is four requests per process and the body receive deadline is
60 seconds. Parser/model execution still needs supervised worker deadlines.
Cancellation does not free the input file or admission slot while its thread
continues running. This design adds a bounded disk copy before decoding.

Third-batch validation: `make verify` passed 1,040 tests with 100% line/branch
coverage; Ruff, mypy and Bandit passed. Strict MkDocs and 100% public-docstring
coverage passed. The isolated Python 3.10 installed wheel passed OpenAPI,
real multipart ingestion and typed Parquet round trips. API regressions cover
chunked/false-length bodies, prefixed deployments, admission exhaustion,
receive deadlines, disconnects, exception cleanup and repeated cancellation.
The real API/Parquet CI matrix now covers Python 3.10, 3.12 and 3.14.

The expanded matrix exposed an undeclared HTTPX test dependency on Python 3.14,
where the optional model client is excluded. HTTPX is now an explicit development
dependency; the lockfile and hashed requirements were regenerated without
changing locked package versions. A clean Poetry environment on Python 3.14
passed all 91 tests from the optional-integration job.

F15 follow-up now includes a reproduced exporter limitation: combining `api`
and `hybrid` in a requirements export narrowed `annotated-doc` to Python <3.14,
although the Poetry lock correctly includes it for the API on Python 3.14.
The corresponding hash-required installation rejects the incomplete export.
Use the locked Poetry installation for that combination until the exporter is
corrected; do not hand-edit the generated requirements or bypass hash checks.


## Fourth implementation batch

PAIN redaction now applies to eager records, streamed records, summaries and
explicitly redacted CSV exports. Both XML compatibility wrappers use the shared
field policy, including message/batch IDs, names, accounts and narratives.
Missing values remain missing and repeated unredacted reads retain the original
data. The eager PAIN parser now reads a standard sibling `DbtrAcct`, matching
its streaming reader while retaining the legacy nested-account fallback.

The CAMT wrapper joins balances on original account IDs before redaction.
Masking before that join collapsed distinct accounts into a common key and
could attach another account's balance. Regression coverage uses two accounts
with different balances and verifies the redacted results stay separate.

Reconciliation reports absolute settled volumes per currency. Mixed-currency
matches set the legacy scalar total to `None` instead of adding incompatible
units. Single-currency and empty reports retain their scalar behavior. Direction
aliases are interpreted explicitly; unknown direction codes fail instead of
being silently treated as credits. Fees excluded from settlement remain
excluded from reconciled volumes.

Fourth-batch local validation: `make verify` passed 1,051 tests with 100%
line/branch coverage; Ruff, mypy and Bandit passed. Strict MkDocs and 100%
public-docstring coverage passed. Regression cases exercise masked CSV output,
repeated unredacted reads, account-specific balances, mixed currencies,
three-decimal settled amounts, fee deductions and debit/credit aliases.

## Financial correctness: ordered follow-up

Implemented scoped summary APIs for CSV, OFX, CAMT, PAIN and MT940. Singular
summaries reject multiple scopes; JSON exports retain the complete scope list.
CAMT/MT940 balances remain within statement periods and currencies, including
in the compatibility wrapper. PAIN counts actual payments, and malformed
financial lines/amounts cannot silently produce partial summaries.

CAMT uses booked account amounts for FX entries, preserves foreign detail
amounts in native records, and requires conserving account-currency detail
amounts in batches. Payment identifiers are separate from remittance. Detail
fallbacks cannot copy a sibling payment's parties or reference. MT940 reversal
and debit-balance signs are corrected, and optional funds codes are supported.

Duplicate review preserves unidentified repeated purchases and limits fuzzy
review groups to matching pairs. Incremental persisted hash sets still require
careful scope selection for unidentified overlapping exports; migration tooling
and cross-file occurrence policy remain open. Bank-specific MT940 century
configuration, investment OFX, additional real-bank fixtures and normalized FX
metadata are also still open. These changes do not establish complete format
coverage or production accuracy.

Validation for this follow-up: `make verify` passed with 1,079 passed, five
skipped and five slow tests deselected; 100% line/branch coverage, Ruff, mypy
and Bandit passed. All five slow performance contracts passed separately.
Strict MkDocs and 100% docstring checks passed. These are local results.
