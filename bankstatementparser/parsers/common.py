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

"""Common utilities and column groups for bank statement parsers."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from ..input_validator import InputValidator, ValidationError
from ..record_types import SummaryRecord

# Synonyms are matched after _normalized_name(), which lowercases,
# folds accents (Libellé -> libelle), and strips non-alphanumerics —
# so every entry here is in that folded form. German (DE), French
# (FR), and Spanish (ES) bank-export headers widen the deterministic
# CSV path before anything falls through to the LLM.
CSV_COLUMN_GROUPS: dict[str, set[str]] = {
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


def _normalize_delimiters(text: str) -> str:
    """Normalize comma and period decimal delimiters in monetary strings."""
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")
    if "," in text:
        return text.replace(",", ".")
    return text


def _parse_amount(value: object) -> Decimal | None:
    """Tolerantly parse a locale-formatted amount into a Decimal."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = _normalize_delimiters(text)
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


def _summary_text(value: object) -> str | None:
    """Normalize missing dataframe metadata without inventing an identity."""
    if value is None or pd.isna(value):
        return None
    return str(value).strip() or None


def _init_summary_group(
    account: str | None, currency: str | None
) -> SummaryRecord:
    """Initialize a summary dictionary for an account and currency pair."""
    return {
        "account_id": account,
        "currency": currency,
        "statement_date": None,
        "transaction_count": 0,
        "total_amount": Decimal("0"),
        "opening_balance": None,
        "closing_balance": None,
    }


def _update_summary_row(
    summary: SummaryRecord, row: dict[str, object]
) -> None:
    """Accumulate a transaction row into an account summary record."""
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


def _grouped_summaries(df: pd.DataFrame) -> list[SummaryRecord]:
    """Aggregate canonical rows without adding different accounts or currencies."""
    groups: dict[tuple[str | None, str | None], SummaryRecord] = {}
    for row in df.to_dict("records"):
        account = _summary_text(row.get("account_id"))
        raw_currency = _summary_text(row.get("currency"))
        currency = raw_currency.upper() if raw_currency else None
        key = (account, currency)
        if key not in groups:
            groups[key] = _init_summary_group(account, currency)
        _update_summary_row(groups[key], row)
    return list(groups.values()) or [_init_summary_group(None, None)]
