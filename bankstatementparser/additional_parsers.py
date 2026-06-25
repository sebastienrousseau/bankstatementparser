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
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from .base_parser import BankStatementParser
from .camt_parser import CamtParser
from .input_validator import InputValidator, ValidationError
from .pain001_parser import Pain001Parser
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
    # NFKD + ASCII-encode folds accented characters to their base
    # letter (é -> e) so French/Spanish headers match their
    # unaccented synonym entries.
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
        # Silently dropping undecodable bytes (errors="ignore")
        # could corrupt amounts and descriptions mid-token.
        raise ValidationError(
            f"File is not valid UTF-8: {path} ({exc})"
        ) from exc


def _parse_amount(value: object) -> Decimal | None:
    """Tolerantly parse a locale-formatted amount into a Decimal.

    Returns ``None`` when the value is blank or unparseable —
    callers that require an amount must use :func:`_require_amount`
    so garbage fails loudly instead of becoming ``0.0``.
    """
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
    """Parse an amount where a blank cell legitimately means zero.

    Used for CSV credit/debit column pairs, where an empty cell on
    one side is the normal representation of "no entry". Non-blank
    garbage still fails loudly.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal("0")
    if not str(value).strip():
        return Decimal("0")
    return _require_amount(value, context=context)


class CsvStatementParser(BankStatementParser):
    """Parse bank statement CSV files with basic column normalization."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and register the CSV file for parsing.

        Args:
            file_name: Path to the CSV statement file.

        Raises:
            ValidationError: If the path fails input validation.
            FileNotFoundError: If the file does not exist.
        """
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
        """Parse the CSV file into a normalized DataFrame.

        Columns are mapped onto the logical names ``date``,
        ``description``, ``amount``, ``currency``, ``balance``,
        ``account_id``, and ``transaction_id`` where present. Results
        are cached; repeat calls return a copy.

        Returns:
            pd.DataFrame: One row per transaction.

        Raises:
            ValidationError: If an amount cell cannot be parsed.
        """
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        raw_df = pd.read_csv(self._path, sep=None, engine="python")
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

    def get_summary(self) -> SummaryRecord:
        """Summarize the parsed CSV statement.

        Returns:
            SummaryRecord: Account id, statement date, transaction
            count, total amount, opening/closing balances (when a
            balance column exists), and currency.

        Raises:
            ValidationError: If an amount cell cannot be parsed.
        """
        df = self.parse()
        balance = df["balance"] if "balance" in df.columns else pd.Series()
        return {
            "account_id": (
                df["account_id"].dropna().astype(str).iloc[0]
                if "account_id" in df.columns and not df.empty
                else None
            ),
            "statement_date": (
                df["date"].dropna().astype(str).iloc[-1]
                if "date" in df.columns and not df.empty
                else None
            ),
            "transaction_count": len(df),
            "total_amount": (
                sum(df["amount"].dropna(), Decimal("0"))
                if "amount" in df.columns
                else Decimal("0")
            ),
            "opening_balance": (
                _parse_amount(balance.iloc[0]) if not balance.empty else None
            ),
            "closing_balance": (
                _parse_amount(balance.iloc[-1]) if not balance.empty else None
            ),
            "currency": (
                df["currency"].dropna().astype(str).iloc[0]
                if "currency" in df.columns and not df.empty
                else None
            ),
        }


class OfxParser(BankStatementParser):
    """Parse OFX and QFX bank statement files."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and read the OFX/QFX file.

        Args:
            file_name: Path to the OFX or QFX statement file.

        Raises:
            ValidationError: If the path fails input validation.
            FileNotFoundError: If the file does not exist.
        """
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
        """Parse ``<STMTTRN>`` blocks into a DataFrame.

        Results are cached; repeat calls return a copy.

        Returns:
            pd.DataFrame: One row per transaction with ``date``,
            ``description``, ``amount``, ``currency``, ``account_id``,
            ``transaction_id``, and ``transaction_type`` columns.

        Raises:
            ValidationError: If a TRNAMT value cannot be parsed.
        """
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        currency = self._tag_value(self._text, "CURDEF")
        account_id = self._tag_value(self._text, "ACCTID")
        rows: list[TransactionRecord] = []
        blocks = re.findall(
            r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>|</BANKTRANLIST>))",
            self._text,
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

    def get_summary(self) -> SummaryRecord:
        """Summarize the parsed OFX/QFX statement.

        Returns:
            SummaryRecord: Account id, statement date, transaction
            count, total amount, and currency. OFX carries no balance
            records, so opening/closing balances are ``None``.

        Raises:
            ValidationError: If a TRNAMT value cannot be parsed.
        """
        df = self.parse()
        return {
            "account_id": (
                df["account_id"].dropna().astype(str).iloc[0]
                if "account_id" in df.columns and not df.empty
                else None
            ),
            "statement_date": (
                df["date"].dropna().astype(str).iloc[-1]
                if "date" in df.columns and not df.empty
                else None
            ),
            "transaction_count": len(df),
            "total_amount": (
                sum(df["amount"].dropna(), Decimal("0"))
                if "amount" in df.columns
                else Decimal("0")
            ),
            "opening_balance": None,
            "closing_balance": None,
            "currency": (
                df["currency"].dropna().astype(str).iloc[0]
                if "currency" in df.columns and not df.empty
                else None
            ),
        }


class Mt940Parser(BankStatementParser):
    """Parse MT940 bank statement files."""

    def __init__(self, file_name: str | Path) -> None:
        """Validate and read the MT940 file.

        Args:
            file_name: Path to the MT940 statement file.

        Raises:
            ValidationError: If the path fails input validation.
            FileNotFoundError: If the file does not exist.
        """
        super().__init__(file_name)
        self._path, self._text = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None
        self._opening_balance: Decimal | None = None
        self._closing_balance: Decimal | None = None
        self._account_id: str | None = None
        self._currency: str | None = None

    def parse(self) -> pd.DataFrame:
        """Parse ``:61:``/``:86:`` lines into a DataFrame.

        Also captures the account id (``:25:``) and opening/closing
        balances (``:60F:``/``:62F:``) for :meth:`get_summary`.
        Results are cached; repeat calls return a copy.

        Returns:
            pd.DataFrame: One row per ``:61:`` transaction line.

        Raises:
            ValidationError: If a transaction amount cannot be parsed.
        """
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        rows: list[TransactionRecord] = []
        current: TransactionRecord | None = None

        for raw_line in self._text.splitlines():
            line = raw_line.strip()
            if line.startswith(":25:"):
                self._account_id = line[4:].strip() or None
            elif line.startswith((":60F:", ":62F:")):
                match = re.match(
                    r"^:(60F|62F):[CD](\d{6})([A-Z]{3})([0-9,]+)$", line
                )
                if match is not None:
                    amount = _parse_amount(match.group(4))
                    self._currency = match.group(3)
                    if match.group(1) == "60F":
                        self._opening_balance = amount
                    else:
                        self._closing_balance = amount
            elif line.startswith(":61:"):
                match = re.match(
                    r"^:61:(\d{6})(?:\d{4})?([CD])([0-9,]+)(.*)$",
                    line,
                )
                if match is not None:
                    sign = (
                        Decimal("-1")
                        if match.group(2) == "D"
                        else Decimal("1")
                    )
                    current_record: TransactionRecord = {
                        "date": match.group(1),
                        "amount": sign
                        * _require_amount(
                            match.group(3),
                            context="MT940 :61: line",
                        ),
                        "transaction_id": match.group(4).strip() or None,
                        "account_id": self._account_id,
                        "currency": self._currency,
                        "description": None,
                    }
                    current = current_record
                    rows.append(current_record)
            elif line.startswith(":86:") and current is not None:
                current["description"] = line[4:].strip() or None

        self._parsed_df = pd.DataFrame(rows)
        return self._parsed_df.copy()

    def get_summary(self) -> SummaryRecord:
        """Summarize the parsed MT940 statement.

        Returns:
            SummaryRecord: Account id, statement date, transaction
            count, total amount, opening/closing balances, and
            currency taken from the balance lines.

        Raises:
            ValidationError: If a transaction amount cannot be parsed.
        """
        df = self.parse()
        return {
            "account_id": self._account_id,
            "statement_date": (
                df["date"].dropna().astype(str).iloc[-1]
                if "date" in df.columns and not df.empty
                else None
            ),
            "transaction_count": len(df),
            "total_amount": (
                sum(df["amount"].dropna(), Decimal("0"))
                if "amount" in df.columns
                else Decimal("0")
            ),
            "opening_balance": self._opening_balance,
            "closing_balance": self._closing_balance,
            "currency": self._currency,
        }


QfxParser = OfxParser


def detect_statement_format(file_name: str | Path) -> str:
    """Detect the parser format for a bank statement file.

    Returns:
        str: One of ``camt``, ``pain001``, ``csv``, ``ofx``, or
        ``mt940``.

    Raises:
        ValidationError: If the path fails input validation or the
            format cannot be detected.
        FileNotFoundError: If the file does not exist.
    """
    path, text = _read_validated_text(file_name)
    suffix = path.suffix.lower()
    lowered = text.lower()

    if suffix == ".csv":
        return "csv"
    if suffix in {".ofx", ".qfx"}:
        return "ofx"
    if suffix in {".mt940", ".sta"}:
        return "mt940"
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
    raise ValidationError(f"Unable to detect statement format: {path}")


def create_parser(
    file_name: str | Path,
    format_name: str | None = None,
) -> BankStatementParser:
    """Create a parser instance from an explicit or detected format.

    Args:
        file_name: Path to the statement file.
        format_name: Explicit format name; when ``None``, the format
            is detected via :func:`detect_statement_format`.

    Returns:
        BankStatementParser: A parser for the selected format.

    Raises:
        ValidationError: If the format is unsupported, the path fails
            input validation, or the format cannot be detected.
        FileNotFoundError: If the file does not exist.
    """
    selected = (format_name or detect_statement_format(file_name)).lower()
    parser_map: dict[str, type[BankStatementParser]] = {
        "camt": CamtParser,
        "pain001": Pain001Parser,
        "csv": CsvStatementParser,
        "ofx": OfxParser,
        "qfx": QfxParser,
        "mt940": Mt940Parser,
    }
    if selected not in parser_map:
        raise ValidationError(f"Unsupported statement format: {selected}")
    parser_cls = parser_map[selected]
    return parser_cls(str(file_name))
