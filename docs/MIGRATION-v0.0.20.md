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
