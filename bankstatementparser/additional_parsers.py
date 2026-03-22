"""Additional bank statement parsers and format detection helpers."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .base_parser import BankStatementParser
from .camt_parser import CamtParser
from .input_validator import InputValidator, ValidationError
from .pain001_parser import Pain001Parser
from .record_types import SummaryRecord, TransactionRecord

CSV_COLUMN_GROUPS = {
    "date": {"date", "bookingdate", "transactiondate", "valuedate"},
    "description": {
        "description",
        "details",
        "memo",
        "narrative",
        "payee",
        "name",
    },
    "amount": {"amount", "transactionamount"},
    "debit": {"debit", "withdrawal", "outflow"},
    "credit": {"credit", "deposit", "inflow"},
    "balance": {"balance", "runningbalance"},
    "currency": {"currency", "ccy"},
    "account_id": {"account", "accountnumber", "iban"},
    "transaction_id": {"id", "transactionid", "reference", "ref"},
}


def _normalized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _read_validated_text(file_name: str | Path) -> tuple[Path, str]:
    validator = InputValidator()
    path = validator.validate_input_file_path(str(file_name))
    return path, path.read_text(encoding="utf-8", errors="ignore")


def _parse_amount(value: object) -> float | None:
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
        return float(normalized)
    except ValueError:
        return None


class CsvStatementParser(BankStatementParser):
    """Parse bank statement CSV files with basic column normalization."""

    def __init__(self, file_name: str | Path) -> None:
        super().__init__(file_name)
        self._path, _ = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None

    def _find_column(
        self, df: pd.DataFrame, logical_name: str
    ) -> str | None:
        candidates = CSV_COLUMN_GROUPS[logical_name]
        for column in df.columns:
            column_name = str(column)
            if _normalized_name(column_name) in candidates:
                return column_name
        return None

    def parse(self) -> pd.DataFrame:
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
            parsed["amount"] = raw_df[amount_col].map(_parse_amount)
        else:
            credit_col = self._find_column(raw_df, "credit")
            debit_col = self._find_column(raw_df, "debit")
            credit = (
                raw_df[credit_col].map(_parse_amount)
                if credit_col
                else pd.Series([0.0] * len(raw_df), index=raw_df.index)
            )
            debit = (
                raw_df[debit_col].map(_parse_amount)
                if debit_col
                else pd.Series([0.0] * len(raw_df), index=raw_df.index)
            )
            parsed["amount"] = credit.fillna(0.0) - debit.fillna(0.0)

        for logical_name in (
            "currency",
            "balance",
            "account_id",
            "transaction_id",
        ):
            source_col = self._find_column(raw_df, logical_name)
            if source_col:
                parsed[logical_name] = raw_df[source_col]

        self._parsed_df = parsed.fillna(value={"amount": 0.0})
        return self._parsed_df.copy()

    def get_summary(self) -> SummaryRecord:
        df = self.parse()
        balance = (
            df["balance"] if "balance" in df.columns else pd.Series()
        )
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
            "transaction_count": int(len(df)),
            "total_amount": float(df["amount"].fillna(0.0).sum()),
            "opening_balance": (
                _parse_amount(balance.iloc[0])
                if not balance.empty
                else None
            ),
            "closing_balance": (
                _parse_amount(balance.iloc[-1])
                if not balance.empty
                else None
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
        super().__init__(file_name)
        self._path, self._text = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None

    def _tag_value(self, source: str, tag: str) -> str | None:
        match = re.search(
            rf"<{tag}>([^<\r\n]+)", source, flags=re.IGNORECASE
        )
        if match is None:
            return None
        return match.group(1).strip()

    def parse(self) -> pd.DataFrame:
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
            rows.append(
                {
                    "date": posted[:8],
                    "description": (
                        self._tag_value(block, "MEMO")
                        or self._tag_value(block, "NAME")
                    ),
                    "amount": _parse_amount(
                        self._tag_value(block, "TRNAMT")
                    )
                    or 0.0,
                    "currency": currency,
                    "account_id": account_id,
                    "transaction_id": self._tag_value(block, "FITID"),
                    "transaction_type": self._tag_value(
                        block, "TRNTYPE"
                    ),
                }
            )

        self._parsed_df = pd.DataFrame(rows)
        return self._parsed_df.copy()

    def get_summary(self) -> SummaryRecord:
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
            "transaction_count": int(len(df)),
            "total_amount": float(df["amount"].fillna(0.0).sum())
            if "amount" in df.columns
            else 0.0,
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
        super().__init__(file_name)
        self._path, self._text = _read_validated_text(file_name)
        self._parsed_df: pd.DataFrame | None = None
        self._opening_balance: float | None = None
        self._closing_balance: float | None = None
        self._account_id: str | None = None
        self._currency: str | None = None

    def parse(self) -> pd.DataFrame:
        if self._parsed_df is not None:
            return self._parsed_df.copy()

        rows: list[TransactionRecord] = []
        current: TransactionRecord | None = None

        for raw_line in self._text.splitlines():
            line = raw_line.strip()
            if line.startswith(":25:"):
                self._account_id = line[4:].strip() or None
            elif line.startswith(":60F:") or line.startswith(":62F:"):
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
                    sign = -1.0 if match.group(2) == "D" else 1.0
                    current_record: TransactionRecord = {
                        "date": match.group(1),
                        "amount": sign
                        * (_parse_amount(match.group(3)) or 0.0),
                        "transaction_id": match.group(4).strip()
                        or None,
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
        df = self.parse()
        return {
            "account_id": self._account_id,
            "statement_date": (
                df["date"].dropna().astype(str).iloc[-1]
                if "date" in df.columns and not df.empty
                else None
            ),
            "transaction_count": int(len(df)),
            "total_amount": float(df["amount"].fillna(0.0).sum())
            if "amount" in df.columns
            else 0.0,
            "opening_balance": self._opening_balance,
            "closing_balance": self._closing_balance,
            "currency": self._currency,
        }


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
    if suffix == ".xml" and (
        "cstmrcdttrfinitn" in lowered or "pain.001" in lowered
    ):
        return "pain001"
    if suffix == ".xml" and (
        "bk to cstmr stmt" in lowered or "camt." in lowered
    ):
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
    """Create a parser instance from an explicit or detected format."""
    selected = (
        format_name or detect_statement_format(file_name)
    ).lower()
    parser_map: dict[str, type[BankStatementParser]] = {
        "camt": CamtParser,
        "pain001": Pain001Parser,
        "csv": CsvStatementParser,
        "ofx": OfxParser,
        "qfx": QfxParser,
        "mt940": Mt940Parser,
    }
    if selected not in parser_map:
        raise ValidationError(
            f"Unsupported statement format: {selected}"
        )
    parser_cls = parser_map[selected]
    return parser_cls(str(file_name))
