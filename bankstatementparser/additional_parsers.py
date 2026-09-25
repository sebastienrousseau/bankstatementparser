# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Additional bank statement parsers and format detection helpers."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import pandas as pd

from .base_parser import BankStatementParser, _single_summary
from .camt_parser import CamtParser
from .input_validator import InputValidator, ValidationError
from .pain001_parser import Pain001Parser
from .plugins import get_registered_loaders
from .record_types import SummaryRecord, TransactionRecord

# Synonyms are matched after _normalized_name(), which lowercases,
# folds accents (Libellé -> libelle), and strips non-alphanumerics —
# so every entry here is in that folded form. German (DE), French
# (FR), and Spanish (ES) bank-export headers widen the deterministic
# CSV path before anything falls through to the LLM.
CSV_COLUMN_GROUPS = {
    "date": {
        "date",
        "bookingdate",
        "transactiondate",
        "valuedate",
        "buchungstag",  # DE
        "dateoperation",  # FR "Date opération"
        "datevaleur",  # FR "Date valeur"
        "fecha",  # ES
        "fechaoperacion",  # ES "Fecha operación"
        "fechavalor",  # ES "Fecha valor"
    },
    "description": {
        "description",
        "details",
        "memo",
        "narrative",
        "payee",
        "name",
        "verwendungszweck",  # DE
        "libelle",  # FR "Libellé"
        "concepto",  # ES
        "descripcion",  # ES "Descripción"
    },
    "amount": {
        "amount",
        "transactionamount",
        "betrag",  # DE
        "value",
        "sum",
        "montant",  # FR
        "importe",  # ES
    },
    "debit": {
        "debit",  # EN; also FR "Débit" after accent folding
        "withdrawal",
        "outflow",
        "soll",  # DE
        "cargo",  # ES
        "adeudo",  # ES
        "debito",  # ES "Débito"
    },
    "credit": {
        "credit",  # EN; also FR "Crédit" after accent folding
        "deposit",
        "inflow",
        "haben",  # DE
        "abono",  # ES
        "ingreso",  # ES
        "credito",  # ES "Crédito"
    },
    "balance": {
        "balance",
        "runningbalance",
        "solde",  # FR
        "saldo",  # ES (and DE)
    },
    "currency": {
        "currency",
        "ccy",
        "devise",  # FR
        "divisa",  # ES
        "moneda",  # ES
    },
    "account_id": {
        "account",
        "accountnumber",
        "iban",
        "compte",  # FR
        "cuenta",  # ES
    },
    "transaction_id": {
        "id",
        "transactionid",
        "reference",  # EN; also FR "Référence" after accent folding
        "ref",
        "referencia",  # ES
    },
}


def _normalized_name(name: str) -> str:
    """Fold a header name to lowercase ASCII alphanumerics for matching."""
    folded = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "", folded.lower())


def _read_validated_text(file_name: str | Path) -> tuple[Path, str]:
    """Validate the path and read its contents as UTF-8 text."""
    validator = InputValidator()
    path = validator.validate_input_file_path(str(file_name))
    try:
        return path, path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"File is not valid UTF-8: {path} ({exc})"
        ) from exc


def _parse_amount(value: object) -> Decimal | None:
    """Tolerantly parse a locale-formatted amount into a Decimal."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            normalized = text.replace(".", "").replace(",", ".")
        else:
            normalized = text.replace(",", "")
    elif "," in text:
        normalized = text.replace(",", ".")
    else:
        normalized = text
    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _require_amount(value: object, *, context: str) -> Decimal:
    """Parse an amount that must be present and valid."""
    amount = _parse_amount(value)
    if amount is None:
        raise ValidationError(f"Unparseable amount {value!r} in {context}")
    return amount


def _amount_or_zero(value: object, *, context: str) -> Decimal:
    """Parse an amount where a blank cell legitimately means zero."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal("0")
    if not str(value).strip():
        return Decimal("0")
    return _require_amount(value, context=context)


def _grouped_summaries(df: pd.DataFrame) -> list[SummaryRecord]:
    """Aggregate canonical rows without adding different accounts or currencies."""
    groups: dict[tuple[str | None, str | None], SummaryRecord] = {}
    for row in df.to_dict("records"):
        account = _summary_text(row.get("account_id"))
        raw_currency = _summary_text(row.get("currency"))
        currency = raw_currency.upper() if raw_currency else None
        key = (account, currency)
        if key not in groups:
            groups[key] = {
                "account_id": account,
                "currency": currency,
                "statement_date": None,
                "transaction_count": 0,
                "total_amount": Decimal("0"),
                "opening_balance": None,
                "closing_balance": None,
            }
        summary = groups[key]
        summary["transaction_count"] += 1
        summary["total_amount"] += _require_amount(
            row.get("amount"), context="summary amount"
        )
        day = _summary_text(row.get("date"))
        if day is not None:
            summary["statement_date"] = day
        balance = _summary_text(row.get("balance"))
        if balance is not None:
            summary["closing_balance"] = _require_amount(
                balance, context="summary balance"
            )
    return list(groups.values()) or [
        {
            "account_id": None,
            "currency": None,
            "statement_date": None,
            "transaction_count": 0,
            "total_amount": Decimal("0"),
            "opening_balance": None,
            "closing_balance": None,
        }
    ]


def _summary_text(value: object) -> str | None:
    """Normalize missing dataframe metadata without inventing an identity."""
    if value is None or pd.isna(value):
        return None
    return str(value).strip() or None


class CsvStatementParser(BankStatementParser):
    """Parse bank statement CSV files with basic column normalization."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and register the CSV file for parsing."""
        super().__init__(file_name)
        self._path, _ = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None

    def _find_column(self, df: pd.DataFrame, logical_name: str) -> str | None:
        """Return the DataFrame column matching a logical name, if any."""
        candidates = CSV_COLUMN_GROUPS[logical_name]
        for column in df.columns:
            column_name = str(column)
            if _normalized_name(column_name) in candidates:
                return column_name
        return None

    def parse(self) -> pd.DataFrame:
        """Parse the CSV file into a normalized DataFrame."""
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        raw_df = pd.read_csv(
            self._path,
            sep=None,
            engine="python",
            dtype=str,
            keep_default_na=False,
        )
        parsed = pd.DataFrame(index=raw_df.index)

        date_col = self._find_column(raw_df, "date")
        if date_col:
            parsed["date"] = raw_df[date_col]

        desc_col = self._find_column(raw_df, "description")
        if desc_col:
            parsed["description"] = raw_df[desc_col]

        amount_col = self._find_column(raw_df, "amount")
        if amount_col:
            parsed["amount"] = raw_df[amount_col].map(
                lambda v: _require_amount(
                    v, context=f"CSV column {amount_col!r}"
                )
            )
        else:
            credit_col = self._find_column(raw_df, "credit")
            debit_col = self._find_column(raw_df, "debit")
            if not credit_col and not debit_col:
                raise ValidationError(
                    "CSV requires an amount, debit, or credit column"
                )
            zero = pd.Series([Decimal("0")] * len(raw_df), index=raw_df.index)
            credit = (
                raw_df[credit_col].map(
                    lambda v: _amount_or_zero(
                        v, context=f"CSV column {credit_col!r}"
                    )
                )
                if credit_col
                else zero
            )
            debit = (
                raw_df[debit_col].map(
                    lambda v: _amount_or_zero(
                        v, context=f"CSV column {debit_col!r}"
                    )
                )
                if debit_col
                else zero
            )
            parsed["amount"] = credit - debit

        for logical_name in (
            "currency",
            "balance",
            "account_id",
            "transaction_id",
        ):
            source_col = self._find_column(raw_df, logical_name)
            if source_col:
                parsed[logical_name] = raw_df[source_col]

        self._parsed_df = parsed
        return self._parsed_df.copy()

    def get_summaries(self) -> list[SummaryRecord]:
        """Summarize CSV rows separately by account and currency.

        A running balance column does not establish an opening balance without
        an explicit timing convention, so opening_balance remains unknown.
        """
        return _grouped_summaries(self.parse())

    def get_summary(self) -> SummaryRecord:
        """Return a single CSV scope, or require get_summaries for mixed files."""
        return _single_summary(self.get_summaries())


class OfxParser(BankStatementParser):
    """Parse OFX and QFX bank statement files."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and read the OFX/QFX file."""
        super().__init__(file_name)
        self._path, self._text = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None

    def _tag_value(self, source: str, tag: str) -> str | None:
        """Return the stripped value of an OFX/SGML tag, or None."""
        match = re.search(rf"<{tag}>([^<\r\n]+)", source, flags=re.IGNORECASE)
        if match is None:
            return None
        return match.group(1).strip()

    def parse(self) -> pd.DataFrame:
        """Parse ``<STMTTRN>`` blocks into a DataFrame."""
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        rows: list[TransactionRecord] = []
        # OFX may contain multiple bank and credit-card statements. Metadata
        # belongs to each statement container, never the entire document.
        statements = re.findall(
            r"<(STMTRS|CCSTMTRS)>(.*?)</\1>",
            self._text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for statement in [body for _, body in statements] or [self._text]:
            currency = self._tag_value(statement, "CURDEF")
            account_id = self._tag_value(statement, "ACCTID")
            blocks = re.findall(
                r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>|</BANKTRANLIST>))",
                statement,
                flags=re.IGNORECASE | re.DOTALL,
            )
            for block in blocks:
                posted = self._tag_value(block, "DTPOSTED") or ""
                transaction_id = self._tag_value(block, "FITID")
                rows.append(
                    {
                        "date": posted[:8],
                        "description": (
                            self._tag_value(block, "MEMO")
                            or self._tag_value(block, "NAME")
                        ),
                        "amount": _require_amount(
                            self._tag_value(block, "TRNAMT"),
                            context=(
                                f"OFX STMTTRN {transaction_id or '(no FITID)'}"
                            ),
                        ),
                        "currency": currency,
                        "account_id": account_id,
                        "transaction_id": transaction_id,
                        "transaction_type": self._tag_value(block, "TRNTYPE"),
                    }
                )

        self._parsed_df = pd.DataFrame(rows)
        return self._parsed_df.copy()

    def get_summaries(self) -> list[SummaryRecord]:
        """Summarize OFX/QFX transactions by account and currency."""
        return _grouped_summaries(self.parse())

    def get_summary(self) -> SummaryRecord:
        """Return a single OFX scope, rejecting mixed account/currency totals."""
        return _single_summary(self.get_summaries())


class Mt940Parser(BankStatementParser):
    """Parse MT940 bank statement files with reversal and multiline support."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and read the MT940 file."""
        super().__init__(file_name)
        self._path, self._text = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None
        self._summaries: list[SummaryRecord] = []

    @staticmethod
    def _empty_summary() -> SummaryRecord:
        """Create an independent statement scope with unknown balances."""
        return {
            "account_id": None,
            "currency": None,
            "statement_date": None,
            "transaction_count": 0,
            "total_amount": Decimal("0"),
            "opening_balance": None,
            "closing_balance": None,
        }

    def parse(self) -> pd.DataFrame:
        """Parse statement-scoped transactions, signed balances and reversals.

        Two-digit dates use Python's explicit 1969-2068 interpretation.
        RC reverses a credit (negative); RD reverses a debit (positive).
        """
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        rows: list[TransactionRecord] = []
        summaries: list[SummaryRecord] = []
        summary = self._empty_summary()
        current: TransactionRecord | None = None
        in_86 = False
        has_scope = False

        for raw_line in self._text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith(":20:") or (
                line.startswith(":25:") and summary["account_id"] is not None
            ):
                if has_scope:
                    summaries.append(summary)
                summary = self._empty_summary()
                current = None
                in_86 = False
                has_scope = True
            if line.startswith(":20:"):
                summary["message_id"] = line[4:].strip() or None
            elif line.startswith(":25:"):
                has_scope = True
                in_86 = False
                current = None
                summary["account_id"] = line[4:].strip() or None
            elif line.startswith(":28C:"):
                summary["statement_id"] = line[5:].strip() or None
                current = None
                in_86 = False
            elif line.startswith((":60F:", ":60M:", ":62F:", ":62M:")):
                has_scope = True
                in_86 = False
                current = None
                match = re.fullmatch(
                    r":(60F|60M|62F|62M):([CD])(\d{6})([A-Z]{3})([0-9,]+)",
                    line,
                )
                if match is None:
                    raise ValidationError("Malformed MT940 balance line")
                currency = match.group(4)
                if summary["currency"] not in (None, currency):
                    raise ValidationError(
                        "Conflicting MT940 statement currencies"
                    )
                summary["currency"] = currency
                amount = _require_amount(
                    match.group(5), context="MT940 balance"
                )
                if match.group(2) == "D":
                    amount = -amount
                balance_key: Literal["opening_balance", "closing_balance"] = (
                    "opening_balance"
                    if match.group(1).startswith("60")
                    else "closing_balance"
                )
                if summary[balance_key] not in (None, amount):
                    raise ValidationError(
                        "Conflicting MT940 statement balances"
                    )
                summary[balance_key] = amount
                summary["statement_date"] = (
                    datetime.strptime(match.group(3), "%y%m%d")
                    .date()
                    .isoformat()
                )
            elif line.startswith(":61:"):
                has_scope = True
                in_86 = False
                match = re.fullmatch(
                    r":61:(\d{6})(?:\d{4})?(RC|RD|EC|ED|C|D)[A-Z]?([0-9,]+)(.*)",
                    line,
                )
                if match is None:
                    raise ValidationError(
                        "Malformed MT940 :61: transaction line"
                    )
                # Debit and credit reversals have the opposite cash direction.
                sign = (
                    Decimal("-1")
                    if match.group(2) in {"D", "RC", "ED"}
                    else Decimal("1")
                )
                amount = sign * _require_amount(
                    match.group(3), context="MT940 :61: line"
                )
                current = {
                    "date": datetime.strptime(match.group(1), "%y%m%d")
                    .date()
                    .isoformat(),
                    "amount": amount,
                    "transaction_id": match.group(4).strip() or None,
                    "account_id": summary["account_id"],
                    "currency": summary["currency"],
                    "description": None,
                }
                rows.append(current)
                summary["transaction_count"] += 1
                summary["total_amount"] += amount
            elif line.startswith(":86:") and current is not None:
                current["description"] = line[4:].strip() or None
                in_86 = True
            elif in_86 and current is not None:
                # Continuation line for :86: narrative
                if re.match(
                    r"^:[0-9]{2}[A-Z]?:", line
                ) is None and not line.startswith("-"):
                    desc = current.get("description") or ""
                    current["description"] = (
                        desc + " " + line
                    ).strip() or None
                else:
                    in_86 = False
                    current = None

        summaries.append(summary)
        self._summaries = summaries
        self._parsed_df = pd.DataFrame(rows)
        return self._parsed_df.copy()

    def get_summaries(self) -> list[SummaryRecord]:
        """Return independent MT940 statement totals and signed balances."""
        self.parse()
        return [summary.copy() for summary in self._summaries]

    def get_summary(self) -> SummaryRecord:
        """Return one MT940 account/currency scope, rejecting mixed files."""
        return _single_summary(self.get_summaries())


QfxParser = OfxParser


def detect_statement_format(file_name: str | Path) -> str:
    """Detect the parser format for a bank statement file."""
    path, text = _read_validated_text(file_name)
    suffix = path.suffix.lower()
    lowered = text.lower()

    if suffix == ".csv":
        return "csv"
    if suffix in {".ofx", ".qfx"}:
        return "ofx"
    if suffix in {".mt940", ".sta"}:
        return "mt940"
    if suffix == ".bai2" or text.startswith("01,") or "\n01," in text:
        return "bai2"
    if suffix == ".mt942" or (":34F:" in text and ":61:" in text):
        return "mt942"
    if suffix == ".xml" and (
        "cstmrcdttrfinitn" in lowered or "pain.001" in lowered
    ):
        return "pain001"
    if suffix == ".xml" and ("bktocstmrstmt" in lowered or "camt." in lowered):
        return "camt"
    if "<ofx>" in lowered or "<banktranlist>" in lowered:
        return "ofx"
    if ":20:" in text and ":61:" in text:
        return "mt940"

    # Check registered loader plugins
    loaders = get_registered_loaders()
    for name in loaders:
        if suffix == f".{name}" or name in suffix:
            return name

    raise ValidationError(f"Unable to detect statement format: {path}")


def create_parser(
    file_name: str | Path,
    format_name: str | None = None,
) -> BankStatementParser:
    """Create a parser instance from an explicit or detected format."""
    selected = (format_name or detect_statement_format(file_name)).lower()
    parser_map: dict[str, type[BankStatementParser]] = {
        "camt": CamtParser,
        "pain001": Pain001Parser,
        "csv": CsvStatementParser,
        "ofx": OfxParser,
        "qfx": QfxParser,
        "mt940": Mt940Parser,
    }
    # Augment with dynamic plugins
    parser_map.update(get_registered_loaders())

    if selected not in parser_map:
        raise ValidationError(f"Unsupported statement format: {selected}")
    parser_cls = parser_map[selected]
    return parser_cls(str(file_name))
