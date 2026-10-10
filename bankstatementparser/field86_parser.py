# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Structured parser for SWIFT MT940/MT942 Field 86 narrative lines.

Extracts structured subfields from slash-delimited (/TAG/value) and
German SEPA GVC-delimited (?00..?63) narrative lines into a typed
Field86Structure record.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class Field86Structure:
    """Structured fields extracted from a SWIFT :86: narrative tag."""

    raw_narrative: str
    transaction_code: str | None = None
    end_to_end_id: str | None = None
    mandate_id: str | None = None
    creditor_id: str | None = None
    creditor_name: str | None = None
    debtor_name: str | None = None
    counterparty_iban: str | None = None
    counterparty_bic: str | None = None
    remittance_info: str | None = None
    purpose_code: str | None = None
    original_amount: Decimal | None = None
    charges_amount: Decimal | None = None
    service_reference: str | None = None
    additional_tags: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert structured fields to a clean dictionary."""
        data = asdict(self)
        if self.original_amount is not None:
            data["original_amount"] = str(self.original_amount)
        if self.charges_amount is not None:
            data["charges_amount"] = str(self.charges_amount)
        return {k: v for k, v in data.items() if v is not None}


_SLASH_SUBFIELD_RE = re.compile(r"/([A-Z0-9]{2,12})/([^/]+)")
_GVC_TAG_RE = re.compile(r"\?(\d{2})([^\?]+)")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_BIC_RE = re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
_CURRENCY_PREFIX_RE = re.compile(r"^[A-Z]{3}")

_TAG_DIRECT_MAP: dict[str, str] = {
    "EREF": "end_to_end_id",
    "MARF": "mandate_id",
    "MREF": "mandate_id",
    "CDTR": "creditor_name",
    "CNAM": "creditor_name",
    "CRED": "creditor_name",
    "DBTR": "debtor_name",
    "DNAM": "debtor_name",
    "DEBT": "debtor_name",
    "CDTRID": "creditor_id",
    "CI": "creditor_id",
    "IBAN": "counterparty_iban",
    "PURP": "purpose_code",
    "CODP": "purpose_code",
    "SVCR": "service_reference",
    "SRV": "service_reference",
}


def _parse_decimal_safe(val: str) -> Decimal | None:
    """Safely convert amount string with comma or dot to Decimal."""
    cleaned = val.strip().replace(",", ".").replace(" ", "")
    cleaned = _CURRENCY_PREFIX_RE.sub("", cleaned)
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _handle_gvc_code(
    code: str,
    val_clean: str,
    res: dict[str, Any],
    remittance_parts: list[str],
    creditor_parts: list[str],
) -> None:
    """Process a single GVC tag and assign to target accumulator."""
    if code == "00":
        res["transaction_code"] = val_clean
    elif code == "10":
        res["end_to_end_id"] = val_clean
    elif code in ("30", "31"):
        key = "counterparty_bic" if code == "30" else "counterparty_iban"
        res[key] = val_clean
    elif code in ("32", "33"):
        creditor_parts.append(val_clean)
    elif "20" <= code <= "29":
        remittance_parts.append(val_clean)
    else:
        res["additional_tags"][f"?{code}"] = val_clean


def _parse_gvc_subfields(text: str, res: dict[str, Any]) -> None:
    """Parse German SEPA GVC codes (?00..?63)."""
    if "?" not in text or not _GVC_TAG_RE.search(text):
        return
    remittance_parts: list[str] = []
    creditor_parts: list[str] = []
    for code, val in _GVC_TAG_RE.findall(text):
        val_clean = val.strip()
        if val_clean:
            _handle_gvc_code(
                code, val_clean, res, remittance_parts, creditor_parts
            )
    if remittance_parts:
        res["remittance_info"] = " ".join(remittance_parts)
    if creditor_parts:
        res["creditor_name"] = " ".join(creditor_parts)


def _handle_slash_tag(
    tag: str,
    val_clean: str,
    res: dict[str, Any],
    remittance_parts: list[str],
) -> None:
    """Process a single slash-delimited tag."""
    if tag in ("REMI", "RMTINF"):
        remittance_parts.append(val_clean)
    elif tag in _TAG_DIRECT_MAP:
        res[_TAG_DIRECT_MAP[tag]] = val_clean
    elif tag in ("BIC", "SWIFT"):
        if val_clean not in ("NOTPROVIDED", "UNDEFINED"):
            res["counterparty_bic"] = val_clean
    elif tag in ("OCMT", "ORAMT"):
        res["original_amount"] = _parse_decimal_safe(val_clean)
    elif tag in ("CHGS", "FEE"):
        res["charges_amount"] = _parse_decimal_safe(val_clean)
    else:
        res["additional_tags"][tag] = val_clean


def _parse_slash_subfields(text: str, res: dict[str, Any]) -> None:
    """Parse SWIFT standard slash-separated subfields (/TAG/value)."""
    if "/" not in text:
        return
    remittance_parts: list[str] = []
    for tag, val in _SLASH_SUBFIELD_RE.findall(text):
        val_clean = val.strip()
        if val_clean:
            _handle_slash_tag(tag, val_clean, res, remittance_parts)
    if remittance_parts and not res.get("remittance_info"):
        res["remittance_info"] = " ".join(remittance_parts)


def _detect_iban_bic_fallback(text: str, res: dict[str, Any]) -> None:
    """Fallback regex detection for IBAN and BIC if not yet discovered."""
    if not res.get("counterparty_iban"):
        iban_match = _IBAN_RE.search(text)
        if iban_match:
            res["counterparty_iban"] = iban_match.group(0)

    if not res.get("counterparty_bic"):
        bic_match = _BIC_RE.search(text)
        if bic_match:
            candidate = bic_match.group(0)
            if candidate not in ("NOTPROVIDED", "UNDEFINED"):
                res["counterparty_bic"] = candidate


def parse_field_86(narrative: str | None) -> Field86Structure:
    """Parse a raw SWIFT Field 86 narrative string into structured components.

    Handles both SWIFT standard slash-separated tags (/EREF/, /REMI/, etc.)
    and German SEPA GVC question-mark codes (?00, ?20, ?32, etc.).

    Args:
        narrative: Raw :86: string or None.

    Returns:
        Structured Field86Structure dataclass with extracted fields.
    """
    if not narrative or not narrative.strip():
        return Field86Structure(raw_narrative="")

    text = narrative.strip()
    res: dict[str, Any] = {
        "raw_narrative": text,
        "additional_tags": {},
    }

    _parse_gvc_subfields(text, res)
    _parse_slash_subfields(text, res)
    _detect_iban_bic_fallback(text, res)

    if not res["additional_tags"]:
        res["additional_tags"] = None

    return Field86Structure(**res)
