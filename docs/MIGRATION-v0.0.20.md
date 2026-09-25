<!-- SPDX-License-Identifier: Apache-2.0 OR MIT -->

# Migration notes for the v0.0.20 branch

These notes describe the current remediation changes, before release.

## Transaction identity

`Transaction.transaction_hash` now returns `v2:` followed by a SHA-256 digest.
The identity includes account, currency, effective date, normalized description,
exact Decimal amount, and bank transaction ID/reference when available.
`Deduplicator.primary_hash` uses that identity. An equal amount and booking date
alone no longer establishes an exact duplicate.

Rebuild persisted seen-hash sets from retained normalized transactions before
re-ingestion. Old digests cannot be converted without their source records. Keep
an export of the old state and reconcile counts during migration. Missing bank
IDs still limit the certainty of duplicate detection; review suspected matches.

## Parsing and financial output

- CSV parsing retains text until numeric conversion, preserving account leading
  zeros and exact decimal strings. A CSV without amount/debit/credit columns now
  fails validation instead of producing zero-valued rows.
- MT940 dates become ISO `YYYY-MM-DD` strings. The adapter currently uses the
  standard Python two-digit-year window: 1969–2068. Use explicit four-digit dates
  for archival data outside that window. Generic transaction models no longer
  guess a year from a six-digit string.
- OFX bank/card statement containers retain their own account and currency.
- CAMT streaming expands transaction details like eager parsing. Missing
  required entry fields and ambiguous batch detail amounts raise errors. Nested
  booked transaction amounts are supported; FX conversion is not inferred.
- Analytics accepts CAMT field names, rejects invalid amounts, and preserves
  native Decimal precision. Missing currency is `UNKNOWN`, never guessed EUR.
  Consumers needing display rounding must choose a currency-aware policy.
- Parquet exports use Arrow logical decimal/date types instead of stringifying
  object columns. Consumers expecting strings must explicitly cast them.

## Reconciliation

Currency is required for matching. `InstdAmt` represents an unsigned outgoing
payment and is compared with a debit statement. Generic `amount` fields must be
signed. References match exactly, placeholder references are ignored, and
conflicting accounts or dates beyond `max_date_gap_days` (default seven) prevent
a match when those fields are present. Missing fields do not prove consistency.

Partial deductions require an explicit `fee_tolerance=Decimal("...")`; the
default is zero. Ambiguous candidates remain unmatched. Verify unmatched counts
and review outcomes before relying on automated downstream posting. `reconciled_volume_by_currency` reports absolute settled amounts separately
for each matched currency, retaining Decimal precision (strings in JSON).
The legacy `total_reconciled_volume` is now `None` / JSON `null` for mixed-currency
matches. It remains a Decimal for a single matched currency and zero for no
matches. No exchange rate is inferred. Recognized debit/credit aliases override
amount signs; unsupported explicit direction codes now raise `ValueError`.

## API, privacy and forensic results

Install the `[api]` extra again to obtain the required multipart dependency.
OpenAPI and health metadata now use the actual package version. Ingestion runs
in a worker thread and oversized uploads clean up their temporary file. Deploy
with the new per-process defaults: four admitted requests, a 60-second body
receive deadline, and a raw body cap of the file limit plus 64 KiB multipart
overhead. Configure `max_concurrent_ingests` and `upload_timeout` on `create_app`.
Excess capacity returns 503, body timeout 408, malformed Content-Length 400,
and oversized bodies 413 before multipart decoding. The exact file cap remains
in force after decoding. A disk-backed request spool adds bounded disk I/O.
Cancellation retains the worker slot and input until ingestion exits. These
limits multiply with the number of server processes; gateway authentication,
rate limits and supervised worker execution deadlines remain deployment work.

Python parsers return full records by default. Pass `redact_pii=True` for CAMT record redaction or PAIN eager parsing,
streaming and summaries. PAIN's `parse(output_file=..., redact_pii=True)` now
writes masked CSV data. Its compatibility wrapper also masks party names,
accounts and narratives. Missing values stay missing. Redaction includes message,
batch and statement identifiers, and never mutates the retained XML tree.
The CAMT compatibility wrapper attaches account balances before masking IDs,
so separate accounts remain separate even when their displayed IDs are equal. CLI console output masks identities and narratives; regular and hybrid file
exports contain full records, while legacy CLI streaming exports follow
`--show-pii`. Python exports reflect the supplied records. Masked records are not a
claim of irreversible anonymization.

PDF forensic verdicts add `INVALID`, `INDETERMINATE`, and `NO_INDICATORS`.
`GENUINE` remains an enum member for compatibility but is no longer emitted.
Heuristic risk findings, including the legacy `is_tampered` field, do not prove
forgery or establish authenticity.


## PDF completeness and crop provenance

`VisionExtractor(max_pages=5)` now rejects a document exceeding its page budget
before rendering or sending data to a model. Increase the explicit budget when
appropriate; the previous behavior silently returned only the first pages.

A single sparse-text page now routes the entire PDF to vision, even when other
pages have abundant searchable text. This includes blank or cover pages because
text extraction alone cannot distinguish them safely from scanned content. A
configured vision model is required for this path.

Strip-mode rows carry the actual original page index and remapped page-relative
bounding boxes. Identity alone no longer removes a row: overlap merging needs
strong spatial overlap with a matching observation from the adjacent strip.
Repeated observations without boxes remain in the result. Review unverifiable
statements and balance discrepancies; neither model output nor inferred boxes
are guaranteed to identify every bank transaction correctly.


## Recurring-payment analytics

Recurrence groups now include account and payment direction. `RecurringPattern`
adds an optional `account_id` field, also present in serialized output. Unknown
accounts share their own bucket and cannot be attributed to known accounts.
`is_income` now means a cash inflow determined by bank direction or amount sign,
not a salary keyword or a tax classification. Amounts remain positive magnitudes.

`min_occurrences` must be at least two and counts distinct booking dates.
Same-day repeats remain in occurrence totals and transaction dates but cannot
fabricate or shorten a schedule. Zero-value rows do not create patterns.


## Scoped summaries and booked amounts

Use `get_summaries()` for files containing multiple accounts, currencies or
statement periods. `get_summary()` raises `ValueError` when more than one scope
exists; it no longer selects the first statement or adds unrelated currencies.
JSON exports include a `summaries` array and retain `summary` only for a single
scope (otherwise null). External parsers retain their single-summary default.
CSV and OFX totals group by account/currency; CAMT and MT940 retain statement
boundaries. CAMT counts booked entries, not expanded payment details. PAIN
counts actual payments instead of trusting the header count. CSV running
balances do not establish opening balances, which now remain null.

CAMT totals and transaction `Amount`/`Currency` use booked account amounts.
Native records retain foreign `TransactionAmount`, `CounterValueAmount` and
`InstructedAmount` with their currencies when present. A batch must provide
unambiguous account-currency detail amounts that conserve its booked total.
No exchange rate is inferred. `EndToEndId` and `AcctSvcrRef` are separate from
remittance text; normalization retains the end-to-end ID for reconciliation.
Missing detail fields cannot borrow values from another payment in the batch.

MT940 `RC` is negative and `RD` positive; balance `D` is negative. The optional
funds code following the debit/credit mark does not change its sign. Malformed
transaction/balance lines and conflicting statement currencies or balances
raise errors. Statement-level `:86:` after a closing balance cannot overwrite
transaction narrative. Two-digit dates retain the documented 1969-2068 window.
The reversal and funds-code interpretation follows the
[ING MT940 format guide](https://business.ing.ro/ing2/ingdocuments/MT940-MT942-file-formats.pdf).


The CAMT compatibility wrapper now joins balances by statement position and
exposes `BalancesByCurrency`. Legacy top-level balance codes are populated only
for single-currency balances. `get_account_balances()` adds `StatementIndex`.

`Deduplicator.deduplicate()` requires a usable payment ID for exact duplicate
groups. Identical purchases without an ID remain separate transactions;
`NONREF`, `NOTPROVIDED`, `UNKNOWN` and `N/A` are not usable IDs. Probable groups
contain only the matching pair, and exclude already identified exact duplicates.
The separate `dedupe_by_hash()` incremental filter still uses occurrence counts
against the supplied persisted set; without bank IDs, overlapping exports need
operator validation because fingerprints alone cannot establish identity.


## Streaming resource controls

For file-backed XML, use `CamtParser(path, lazy=True)` or
`Pain001Parser(path, lazy=True)` followed by `parse_streaming()`. This validates
the path and size immediately, then reads XML directly from disk during
iteration. Syntax errors can therefore occur after earlier rows were yielded;
commit downstream imports only after iteration finishes successfully. Closing
the iterator releases its file handle. Calling `parse()`, a summary method or
accessing `tree` deliberately materializes the document. The default eager
constructor remains compatible. Memory-backed CAMT factories retain their input.

Streaming memory depends on the largest entry/payment and parser read buffer;
collecting rows into a list defeats this bound. Completed statement and payment
containers are released. Prefixed PAIN namespaces now work in eager and streaming
paths while foreign extension elements retain their namespaces.

`iter_files_parallel(paths, max_workers=4, max_pending=8)` yields input-ordered
results while retaining at most eight submitted futures. The path iterable is
consumed incrementally, and repeated paths retain separate results.
`parse_files_parallel()` accepts the same pending limit but returns a complete
list. Both APIs still materialize each individual file's DataFrame. Closing the
iterator cancels queued work and waits for running workers; this is not an
execution deadline or a byte-level memory limit.


## API execution deadlines

`create_app()` now runs each ingestion in a disposable Python interpreter and
sets `ingest_timeout=120.0` seconds, including interpreter startup. Exceeding
this execution deadline returns HTTP 504. Timeout or request cancellation kills
and reaps the worker before releasing admission capacity or deleting its input.
The existing upload receive deadline, size limits and admission limit remain.
Set a different positive finite timeout for larger permitted workloads.

Process isolation adds startup overhead and requires permission to start a
Python subprocess using the service's interpreter and installed dependencies.
Worker configuration must be available through the environment or installed
modules; runtime monkeypatches and in-memory plugin registration in the API
process do not transfer to the worker. Entry-point plugins remain discoverable.
For explicitly trusted embedded deployments, `ingest_timeout=None` opts into
the old thread worker with no execution deadline. A terminated local worker
cannot guarantee cancellation of computation already accepted by a remote model
provider. Direct library calls and parallel batch workers have no new deadline.


## Export schemas and privacy

Streaming XML CSV output uses a stable column set from the parser's typed
record definition, including optional fields first encountered in later rows.
Unknown fields fail explicitly; failure preserves the previous destination.
The CLI now selects lazy XML construction for `--streaming`. CSV export no
longer constructs a DataFrame for every row.

Library CSV/JSON/Parquet exports, CAMT Excel, hledger/beancount and
`IngestResult.to_json()` accept `redact_pii=True`; their defaults retain full
data. The common policy also masks source paths, filenames, transaction hashes
and nested identity fields. Hybrid JSON masks diagnostic text and replaces
review history with redaction markers. Ledger redaction uses generic posting
accounts. These are sharing snapshots, not inputs for reconciliation,
deduplication, lossless round-trips or irreversible-anonymization guarantees.

CLI CAMT, PAIN and hybrid-ingest exports now follow `--show-pii` consistently:
identities are masked unless that flag is supplied. Hybrid console diagnostics
are masked too. Amounts, dates, currencies and extraction method remain visible.

`export_parquet_stream(records, path, schema=arrow_schema, batch_size=10000)`
accepts an iterable of mappings, writes bounded batches to a temporary file,
and atomically replaces the destination only after successful completion. It
returns a row count rather than retaining output bytes. Define every permitted
field in the Arrow schema and choose sufficient Decimal precision/scale;
unknown fields, missing non-nullable values and incompatible amounts fail.
Use string fields for identities when enabling redaction. Existing
`export_parquet()` and `parser.to_parquet()` remain eager byte-returning APIs.
