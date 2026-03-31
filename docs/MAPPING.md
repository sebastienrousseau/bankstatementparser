# XML Tag to DataFrame Column Mapping

Maps ISO 20022 XML elements to the DataFrame columns produced by each parser. Use this reference when integrating Bank Statement Parser into ERP systems, data pipelines, or reconciliation workflows.

## CAMT.053 — Bank-to-Customer Statement

Parsed by `CamtParser`. Output from `parse()` and `get_transactions()`.

### Transaction Fields

| DataFrame Column | XML Path | Type | Description |
|---|---|---|---|
| `Amount` | `Ntry/Amt` | float | Transaction amount (negative for debits) |
| `Currency` | `Ntry/Amt/@Ccy` | str | ISO 4217 currency code |
| `DrCr` | `Ntry/CdtDbtInd` | str | `"CRDT"` (credit) or `"DBIT"` (debit) |
| `Debtor` | `Ntry//Dbtr/Nm` | str | Debtor party name |
| `Creditor` | `Ntry//Cdtr/Nm` | str | Creditor party name |
| `Reference` | `Ntry//Ustrd` | str | Unstructured remittance information |
| `ValDt` | `Ntry/ValDt/Dt` or `Ntry/ValDt/DtTm` | str | Value date (ISO 8601) |
| `BookgDt` | `Ntry/BookgDt/Dt` or `Ntry/BookgDt/DtTm` | str | Booking date (ISO 8601) |
| `AccountId` | `Stmt/Acct/Id/IBAN` or `Stmt/Acct/Id/Othr/Id` | str | Account identifier |

### Balance Fields

Output from `get_account_balances()`.

| DataFrame Column | XML Path | Type | Description |
|---|---|---|---|
| `Amount` | `Bal/Amt` | float | Balance amount (negative for debits) |
| `Currency` | `Bal/Amt/@Ccy` | str | ISO 4217 currency code |
| `Code` | `Bal/Tp/CdOrPrtry/Cd` | str | Balance type: `OPBD` (opening), `CLBD` (closing), `CLAV` (closing available) |
| `Description` | — | str | Human-readable label derived from `Code` |
| `CreditDebit` | `Bal/CdtDbtInd` | str | `"CRDT"` or `"DBIT"` |
| `Date` | `Bal/Dt/Dt` or `Bal/Dt/DtTm` | str | Balance date (ISO 8601) |
| `AccountId` | `Stmt/Acct/Id/IBAN` or `Stmt/Acct/Id/Othr/Id` | str | Account identifier |

### Statement Stats

Output from `get_statement_stats()`.

| DataFrame Column | XML Path | Type | Description |
|---|---|---|---|
| `AccountId` | `Stmt/Acct/Id/IBAN` | str | Account identifier |
| `StatementId` | `Stmt/Id` | str | Statement identifier |
| `EntryCount` | count of `Stmt/Ntry` | int | Number of transaction entries |
| `TotalCredits` | sum of credit `Ntry/Amt` | float | Total credit amount |
| `TotalDebits` | sum of debit `Ntry/Amt` | float | Total debit amount |
| `NetAmount` | credits - debits | float | Net balance change |

---

## PAIN.001 — Credit Transfer Initiation

Parsed by `Pain001Parser`. Output from `parse()`.

### Payment Fields

| DataFrame Column | XML Path | Type | Description |
|---|---|---|---|
| `MsgId` | `GrpHdr/MsgId` | str | Message identification |
| `CreDtTm` | `GrpHdr/CreDtTm` | str | Creation date and time |
| `NbOfTxs` | `GrpHdr/NbOfTxs` | str | Number of transactions |
| `InitgPty` | `GrpHdr/InitgPty/Nm` | str | Initiating party name |
| `PmtInfId` | `PmtInf/PmtInfId` | str | Payment information identifier |
| `PmtMtd` | `PmtInf/PmtMtd` | str | Payment method (e.g., `"TRF"`) |
| `ReqdExctnDt` | `PmtInf/ReqdExctnDt` | str | Requested execution date |
| `CtrlSum` | `PmtInf/CtrlSum` | str | Control sum for the payment batch |
| `ChrgBr` | `PmtInf/ChrgBr` | str | Charge bearer (e.g., `"SLEV"`) |
| `DbtrNm` | `PmtInf/Dbtr/Nm` | str | Debtor name |
| `DbtrIBAN` | `PmtInf/DbtrAcct/Id/IBAN` | str | Debtor IBAN |
| `DbtrBIC` | `PmtInf/DbtrAgt/FinInstnId/BIC` | str | Debtor bank BIC |
| `EndToEndId` | `CdtTrfTxInf/PmtId/EndToEndId` | str | End-to-end transaction identifier |
| `InstdAmt` | `CdtTrfTxInf/Amt/InstdAmt` | str | Instructed amount |
| `Currency` | `CdtTrfTxInf/Amt/InstdAmt/@Ccy` | str | ISO 4217 currency code |
| `CdtrBIC` | `CdtTrfTxInf/CdtrAgt/FinInstnId/BIC` | str | Creditor bank BIC |
| `CdtrNm` | `CdtTrfTxInf/Cdtr/Nm` | str | Creditor name |
| `CdtrIBAN` | `CdtTrfTxInf/CdtrAcct/Id/IBAN` | str | Creditor IBAN |

---

## CSV — Bank Statement CSV

Parsed by `CsvStatementParser`. Column headers are normalized automatically.

| DataFrame Column | Recognized Input Headers | Type |
|---|---|---|
| `date` | `Date`, `Transaction Date`, `Booking Date`, `Buchungstag` | str |
| `description` | `Description`, `Narrative`, `Details`, `Verwendungszweck` | str |
| `amount` | `Amount`, `Value`, `Sum`, `Betrag` | float |

Split credit/debit columns (`Credit`/`Debit`, `Haben`/`Soll`) are detected and merged into a single signed `amount`.

---

## OFX / QFX — Open Financial Exchange

Parsed by `OfxParser` / `QfxParser`. Tags extracted via regex.

| DataFrame Column | OFX Tag | Type | Description |
|---|---|---|---|
| `date` | `<DTPOSTED>` | str | Transaction date (YYYYMMDD) |
| `amount` | `<TRNAMT>` | float | Transaction amount |
| `description` | `<NAME>` or `<MEMO>` | str | Transaction description |
| `type` | `<TRNTYPE>` | str | Transaction type (e.g., `DEBIT`, `CREDIT`) |
| `id` | `<FITID>` | str | Financial institution transaction ID |

---

## MT940 — SWIFT Statement

Parsed by `Mt940Parser`.

| DataFrame Column | MT940 Field | Type | Description |
|---|---|---|---|
| `date` | `:61:` (positions 1–6) | str | Transaction date (YYMMDD) |
| `amount` | `:61:` (amount portion) | float | Transaction amount |
| `type` | `:61:` (C/D indicator) | str | `"C"` (credit) or `"D"` (debit) |
| `description` | `:86:` | str | Transaction narrative |
| `account_id` | `:25:` | str | Account identification |

Opening balance (`:60F:`) and closing balance (`:62F:`) are parsed for the statement summary.

---

## Transaction Model — Normalized Record

The `Transaction` class (Pydantic model) normalizes records from any parser into a common schema. Used by the `Deduplicator`.

| Field | Type | Description |
|---|---|---|
| `account_id` | str or None | Account identifier |
| `currency` | str or None | ISO 4217 currency code |
| `amount` | Decimal | Transaction amount (exact precision) |
| `booking_date` | date or None | Booking date |
| `value_date` | date or None | Value date |
| `description` | str or None | Original description |
| `normalized_description` | str | Lowercased, whitespace-collapsed description (for matching) |
| `reference` | str or None | Transaction reference |
| `transaction_id` | str or None | Bank-assigned transaction ID |
| `counterparty` | str or None | Debtor or creditor name |
| `source` | str or None | Data source label |
| `source_index` | int or None | Row index in source |

Create from any parser output:

```python
from bankstatementparser import Transaction

tx = Transaction.from_record(parser.parse().iloc[0], source="bank_a")
```

---

## Deduplication Result

Output of `Deduplicator.deduplicate()`.

| Field | Type | Description |
|---|---|---|
| `unique_transactions` | list[Transaction] | Transactions with no duplicates |
| `exact_duplicates` | list[ExactDuplicateGroup] | Groups sharing an identical primary hash |
| `suspected_matches` | list[MatchGroup] | Groups flagged by similarity (with `confidence` score and `reason`) |
