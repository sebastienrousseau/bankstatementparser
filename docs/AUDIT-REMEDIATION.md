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
| F02 CAMT eager/streaming divergence | Both public paths share transaction expansion; nested `TxAmt` supported; ambiguous or nonconserving batches fail | Broader bank FX fixtures and normalized foreign-amount metadata |
| F03 MT940 dates | Adapter emits ISO dates before model coercion; model rejects ambiguous six-digit dates | Configurable bank-specific date-century policy |
| F04 OFX accounts | Transaction metadata scoped to each bank/card statement | Investment OFX |
| F05 CSV precision | Read textual cells before Decimal conversion; preserve leading zeros; reject missing amount columns | Explicit dialect and date-format configuration |
| F06 transaction identity | Versioned account/currency-scoped hashes; distinct IDs excluded from fuzzy matching; description included in primary key | Occurrence-aware identity when bank IDs are missing and persisted-state migration tooling |
| F07 reconciliation | Indexed candidate lookup; require currency/direction compatibility; exact references; explicit fee tolerance; reject ambiguous candidates and conflicting dates/accounts; per-currency settled volumes | Broader settlement corpus; many-to-one settlements |
| F08 analytics | Recognize parser field aliases; reject invalid amounts; retain Decimal precision; unknown currency is explicit; recurrence isolates accounts/directions and requires distinct dates | Average daily balance and calendar-aware projections |
| F09 API installation | Declare multipart dependency, resolve real FastAPI annotations, report package version; real API/Parquet CI covers Python 3.10, 3.12 and 3.14 | Installed-wheel matrix enforced; optional model stack remains Python <3.14 |
| F10 API resources | Clean temporary files; ingest outside event loop; bound pre-multipart body size, admissions and receive time; retain cancelled workers until completion | Provider-side cancellation and deployment memory limits |
| F11 PDF forensics | Invalid/uninspected documents no longer imply authenticity; clean inspection means `NO_INDICATORS` | Calibrated risk scoring, signature verification and real-document corpus |
| F12 privacy | CAMT opt-in redaction covers parties, identifiers and narratives; CLI displays use common sensitive-field vocabulary; PAIN eager/streaming/summary/CSV and compatibility-wrapper parity | End-to-end export/provenance policy |
| F13 hybrid completeness | Reject over-budget PDFs; route mixed text/scanned files to vision; close native render resources; map crop coordinates to original pages; merge adjacent crop observations using identity and spatial evidence while preserving multiplicity | Worker/provider budgets; automatic balance verification; real PDF/model accuracy corpus |
| F14 Parquet types | Preserve Arrow Decimal/date/timestamp types; fail unsupported columns explicitly | Explicit canonical schema and bounded streaming writer |
| F15 SBOM validity | UUID serial numbers, textual marker properties, retain dependency references to all locked variants | Offline full-schema validation enforced; marker-aware deployment-specific graphs remain |

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
This reproduced limitation is corrected in the packaging follow-up below; do
not hand-edit generated requirements or bypass hash checks.


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

## Resource controls: streaming and scheduling

File-backed CAMT and PAIN now offer `lazy=True`: construction validates the
path without materializing the document, and streaming reads directly from the
file. Early generator closure closes the file; completed statement/payment
containers are removed. Eager APIs still load a tree explicitly. PAIN supports
prefixed namespaces while preserving foreign extensions. Default construction
remains eager for compatibility, so callers must opt into the bounded path.

`iter_files_parallel()` bounds submitted futures (default twice the worker
count), yields input-ordered results and consumes paths incrementally.
`parse_files_parallel()` shares the scheduler but retains its list result.
Each worker still materializes one file; pending-file limits do not establish
byte limits. Early iterator closure cancels queued work but waits for running
workers. Direct-library/batch deadlines and provider-side cancellation remain open;
the API execution deadline is covered below.

On the local Python 3.12.14 environment, fresh-process streaming measurements
including construction produced the following results. Inputs were generated
single-statement files with one amount per entry/payment; results were consumed
without retaining rows. RSS includes Python, pandas and library imports.

| Format | Rows | Peak RSS (MiB) | Constructor to first row (seconds) |
| --- | ---: | ---: | ---: |
| CAMT | 10,000 | 103.66 | 0.0261 |
| CAMT | 100,000 | 103.62 | 0.0212 |
| PAIN | 10,000 | 103.59 | 0.0246 |
| PAIN | 100,000 | 103.52 | 0.0253 |

This demonstrates stable memory across these generated sizes, not a bound for
arbitrarily large individual XML elements or a real-bank performance claim.

Validation: `make verify` passed with 1,091 passed, five skipped and five slow
tests deselected, 100% line/branch coverage, Ruff, mypy and Bandit. All five
slow performance contracts, strict MkDocs and 100% docstring coverage passed.

## Resource controls: API execution deadlines

API ingestion now defaults to a disposable interpreter with a 120-second
execution deadline, including startup. On timeout or request cancellation, the
worker is killed and reaped before its admission slot or input file is released.
The client receives HTTP 504 for deadline expiry. The deadline covers the local
pipeline, including provider waits. Remote inference already accepted by a
provider may continue independently. Direct library and parallel batch calls
still have no new execution deadline.

`ingest_timeout=None` explicitly restores the legacy thread path for trusted
embedded deployments; it cannot interrupt stuck code. Subprocesses inherit
installed dependencies and environment configuration, not in-memory API-process
plugin registration. Tests exercise real subprocess timeout, cancellation,
nonzero exits and successful CSV ingestion, as well as repeated cancellation
during reaping and a generic HTTP timeout response.

Validation: `make verify` passed with 1,101 passed, five skipped and five slow
tests deselected, 100% line/branch coverage, Ruff, mypy and Bandit. Strict MkDocs
and 100% docstring coverage passed; the final API-focused run passed all 48
cases, including real subprocess ingestion and termination.

## Export and privacy follow-up

CLI streaming CSV uses typed-record columns, writes rows without per-row
DataFrames, selects lazy XML parsing and preserves existing output on failure.
Optional fields that appear late cannot shift values under the wrong header.
The new `export_parquet_stream()` requires an explicit Arrow schema, validates
field coverage and required values, writes bounded batches and atomically
replaces the destination. Existing byte-returning Parquet APIs remain eager.

CSV, JSON, Parquet, CAMT Excel, ledger and hybrid JSON exports expose explicit
redaction. The common policy includes nested identity fields, source paths,
filenames and transaction hashes. Hybrid snapshots mask diagnostics and review
history; ledger snapshots use generic posting accounts. CLI CAMT, PAIN and
hybrid-ingest exports consistently honor `--show-pii`. Redacted data retains
amounts/dates/currencies but is not suitable for identity matching or lossless
review round-trips; masking is not irreversible anonymization.

Validation: `make verify` passed with 1,119 passed, five skipped and five slow
tests deselected, 100% line/branch coverage, Ruff, mypy and Bandit. Strict MkDocs
and 100% docstring coverage passed. Real Arrow tests verify Decimal scale,
redaction and atomic rejection of unrepresentable amounts. Batching tests prove
rows are written before the next batch is consumed.

A macOS/Python 3.10 CI throughput regression was repaired separately by avoiding
unneeded CAMT amount/reference traversal and using direct child lookups. The
unchanged throughput and coverage gates passed across the complete remote
matrix after that correction.


## Packaging follow-up

The requirements generator now projects selected extras from Poetry 2.1 lock
markers before rendering Python/platform conditions. It retains every locked
SHA-256 hash, rejects unsupported sources and does not resolve new versions.
The API/hybrid combination installs with hash verification on Python 3.14.
Regeneration tests cover Boolean alternatives, group markers and platform
conditions. Development dependencies explicitly include the export and schema
validation libraries; locked package versions are unchanged.

CI builds the wheel, installs hash-verified dependencies into separate Python
3.10/3.12/3.14 environments, checks dependency compatibility and exercises
financial CSV precision, lazy XML, typed streaming Parquet and actual API
subprocess ingestion. The wheel includes its PEP 561 marker. Isolated API
workers cannot import a working-directory module that shadows the package.

Security and release-integrity jobs validate generated SBOMs against the
official CycloneDX 1.5 schemas, vendored at a pinned upstream commit with
checksums and license. Schema validation is offline and rejects invalid UUIDs
and malformed property values. The SBOM remains an inventory of the complete
lock rather than a deployment-specific dependency graph.

Local packaging validation: 67 packaging/API regression cases passed; the
final documentation/packaging subset passed 51 cases. Clean hash-required
Python 3.10 and 3.14 environments passed dependency checks and installed-wheel
smokes. Strict MkDocs, 100% docstring coverage, Ruff, mypy and Bandit passed.
The all-extras hashed dependency audit found no known vulnerabilities. Local
full-suite throughput checks failed under concurrent machine load; thresholds
were retained, and remote CI performance acceptance must be checked separately.

Packaging remote acceptance: all Quality Gates, Security, Docs and signature
workflows passed for `3f07002`, including unchanged coverage/throughput gates
and installed-wheel checks on Python 3.10, 3.12 and 3.14.

## Calendar analytics follow-up

Implemented an explicit-period, account/currency-scoped end-of-day average
balance calculation with Decimal amounts and no allocation per calendar day.
Run rates include quiet months and prorate explicit partial reporting periods.
Undated transactions retain totals but no longer produce fabricated rates.
Month-end recurrence tolerates limited missing months; inconsistent intervals
cannot establish cadence solely through their average. Input completeness
remains the caller's responsibility, and recurrence confidence is uncalibrated.
