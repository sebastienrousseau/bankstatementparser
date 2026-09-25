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
| F07 reconciliation | Indexed candidate lookup; require currency/direction compatibility; exact references; explicit fee tolerance; reject ambiguous candidates and conflicting dates/accounts | Broader settlement corpus; many-to-one settlements; per-currency reconciled totals |
| F08 analytics | Recognize parser field aliases; reject invalid amounts; retain Decimal precision; unknown currency is explicit | Average daily balance, recurrence account/direction isolation and calendar-aware projections |
| F09 API installation | Declare multipart dependency, resolve real FastAPI annotations, report package version | Expand installed-wheel and minimum-Python integration matrix |
| F10 API resources | Clean temporary files on oversized uploads; run ingestion outside event loop | Limit request body before multipart parsing, bound concurrent jobs and isolate/time-limit workers |
| F11 PDF forensics | Invalid/uninspected documents no longer imply authenticity; clean inspection means `NO_INDICATORS` | Calibrated risk scoring, signature verification and real-document corpus |
| F12 privacy | CAMT opt-in redaction covers parties, identifiers and narratives; CLI displays use common sensitive-field vocabulary | End-to-end export/provenance policy and PAIN parity |
| F13 hybrid completeness | No implementation in this batch | Page budgets must fail explicitly; mixed PDF routing; strip coordinates and occurrence-preserving merge; worker/provider budgets; automatic balance verification |
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
