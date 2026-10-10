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

"""CAMT.052 and CAMT.054 ISO 20022 streaming report and notification parsers."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import ClassVar, cast

import pandas as pd
from lxml import etree

from ._amounts import iso_decimal
from .base_parser import BankStatementParser, _single_summary
from .exceptions import ParserError
from .input_validator import InputValidator
from .privacy import redact_record
from .record_types import SummaryRecord, TransactionRecord
from .transaction_models import Transaction

logger = logging.getLogger(__name__)


def _strip_ns(tag: str) -> str:
    """Return local XML tag without namespace URI prefix."""
    if tag.startswith("{"):
        return str(etree.QName(tag).localname)
    return tag


def _parse_iso_date(date_text: str | None) -> date | None:
    """Parse ISO date or date-time text into datetime.date."""
    if not date_text or not date_text.strip():
        return None
    cleaned = date_text.strip()
    if len(cleaned) >= 10:
        cleaned_date = cleaned[:10]
        try:
            return date.fromisoformat(cleaned_date)
        except ValueError:
            pass
    return None


def _extract_entry_refs(elem: etree._Element) -> tuple[str | None, str | None]:
    """Extract reference and end-to-end identifier from entry or detail."""
    ref_elems = (
        elem.findall(".//Ustrd")
        + elem.findall(".//{*}Ustrd")
        + elem.findall(".//Strd//Ref")
        + elem.findall(".//{*}Strd//{*}Ref")
        + elem.findall(".//CdtrRefInf/Ref")
        + elem.findall(".//{*}CdtrRefInf/{*}Ref")
    )
    texts = [r.text.strip() for r in ref_elems if r.text and r.text.strip()]
    reference = " ".join(dict.fromkeys(texts)) or None
    e2e = elem.findtext(".//Refs/EndToEndId") or elem.findtext(
        ".//{*}Refs/{*}EndToEndId"
    )
    end_to_end = e2e.strip() if e2e and e2e.strip() else None
    return reference, end_to_end


def _extract_parties(elem: etree._Element) -> tuple[str, str]:
    """Extract debtor and creditor party names from entry or detail."""
    dbtr = (
        elem.findtext(".//Dbtr/Nm")
        or elem.findtext(".//{*}Dbtr/{*}Nm")
        or elem.findtext(".//RltdPties/Dbtr/Nm")
        or elem.findtext(".//{*}RltdPties/{*}Dbtr/{*}Nm")
        or ""
    )
    cdtr = (
        elem.findtext(".//Cdtr/Nm")
        or elem.findtext(".//{*}Cdtr/{*}Nm")
        or elem.findtext(".//RltdPties/Cdtr/Nm")
        or elem.findtext(".//{*}RltdPties/{*}Cdtr/{*}Nm")
        or ""
    )
    return dbtr.strip(), cdtr.strip()


def _parse_entry_records(
    entry: etree._Element,
    account_id: str,
    default_currency: str,
    redact_pii: bool,
) -> list[TransactionRecord]:
    """Extract standardized transaction records from an Ntry XML element."""
    amt_elem = entry.find("Amt")
    if amt_elem is None:
        amt_elem = entry.find("{*}Amt")
    cdt_dbt_elem = entry.find("CdtDbtInd")
    if cdt_dbt_elem is None:
        cdt_dbt_elem = entry.find("{*}CdtDbtInd")
    if amt_elem is None:
        raise ValueError("Transaction entry missing <Amt> element")
    if cdt_dbt_elem is None:
        raise ParserError("Transaction entry missing <CdtDbtInd>")

    currency = amt_elem.get("Ccy") or default_currency
    if not currency:
        raise ParserError("Transaction entry missing currency (Ccy)")

    direction = (cdt_dbt_elem.text or "").strip()
    if direction not in {"CRDT", "DBIT"}:
        raise ParserError(f"Invalid CdtDbtInd: {direction}")

    raw_amt = iso_decimal(amt_elem.text, context="CAMT entry")
    signed_amt = -raw_amt if direction == "DBIT" else raw_amt

    val_dt = (
        entry.findtext("./ValDt/Dt")
        or entry.findtext("./{*}ValDt/{*}Dt")
        or entry.findtext("./ValDt/DtTm")
        or entry.findtext("./{*}ValDt/{*}DtTm")
        or ""
    )
    bkg_dt = (
        entry.findtext("./BookgDt/Dt")
        or entry.findtext("./{*}BookgDt/{*}Dt")
        or entry.findtext("./BookgDt/DtTm")
        or entry.findtext("./{*}BookgDt/{*}DtTm")
        or ""
    )
    ref, e2e = _extract_entry_refs(entry)
    dbtr, cdtr = _extract_parties(entry)

    rec: TransactionRecord = {
        "Amount": signed_amt,
        "Currency": currency,
        "DrCr": direction,
        "Debtor": dbtr,
        "Creditor": cdtr,
        "Reference": ref,
        "EndToEndId": e2e,
        "ValDt": val_dt,
        "BookgDt": bkg_dt,
        "AccountId": account_id,
        "description": ref or f"{direction} {currency} {raw_amt}",
        "amount": signed_amt,
        "date": bkg_dt[:10] if len(bkg_dt) >= 10 else val_dt[:10] or None,
        "currency": currency,
        "account_id": account_id,
    }
    if redact_pii:
        return [cast(TransactionRecord, redact_record(rec))]
    return [rec]


def _build_model(record: TransactionRecord, source: str) -> Transaction:
    """Convert a TransactionRecord dictionary into a unified Transaction."""
    bkg = _parse_iso_date(record.get("BookgDt"))
    val = _parse_iso_date(record.get("ValDt"))
    desc = (
        record.get("description") or record.get("Reference") or "Transaction"
    )
    return Transaction(
        account_id=record.get("AccountId"),
        currency=record.get("Currency") or "USD",
        amount=record["Amount"],
        booking_date=bkg,
        value_date=val or bkg,
        description=desc,
        normalized_description=desc.lower(),
        reference=record.get("Reference"),
        transaction_id=record.get("EndToEndId"),
        source=source,
        source_method="deterministic",
    )


def _clear_element(elem: etree._Element) -> None:
    """Clear processed element and prune preceding siblings from DOM."""
    elem.clear()
    while elem.getprevious() is not None:
        del elem.getparent()[0]


def _init_scope_summary() -> SummaryRecord:
    """Initialize a blank scope summary record."""
    return {
        "account_id": None,
        "currency": None,
        "statement_date": None,
        "transaction_count": 0,
        "total_amount": Decimal("0.00"),
        "opening_balance": None,
        "closing_balance": None,
    }


class _BaseCamtStreamParser(BankStatementParser):
    """Base streaming parser for ISO 20022 CAMT report and notification files."""

    SCOPE_TAG: ClassVar[str] = ""
    DOCUMENT_TAG: ClassVar[str] = ""

    def __init__(
        self,
        file_name: str | Path,
        *,
        xml_bytes: bytes | None = None,
        source_name: str | None = None,
    ) -> None:
        """Initialize parser from path or in-memory XML bytes."""
        super().__init__(file_name)
        self._source_name = source_name or str(file_name)
        if xml_bytes is not None:
            self._xml_bytes = xml_bytes
            self._is_memory = True
        else:
            path = InputValidator().validate_input_file_path(str(file_name))
            self._xml_bytes = path.read_bytes()
            self._is_memory = False
        self._parsed_df: pd.DataFrame | None = None
        self._summaries: list[SummaryRecord] = []

    @classmethod
    def from_string(cls, xml_string: str) -> _BaseCamtStreamParser:
        """Create a parser instance directly from an XML string."""
        raw = xml_string.encode("utf-8")
        InputValidator()._validate_bytes_size(raw)
        return cls("memory.xml", xml_bytes=raw, source_name="memory.xml")

    @classmethod
    def from_bytes(
        cls, xml_bytes: bytes, source_name: str = "memory.xml"
    ) -> _BaseCamtStreamParser:
        """Create a parser instance directly from raw XML bytes."""
        InputValidator()._validate_bytes_size(xml_bytes)
        return cls(source_name, xml_bytes=xml_bytes, source_name=source_name)

    def _handle_metadata_event(
        self,
        tag: str,
        elem: etree._Element,
        summary: SummaryRecord | None,
        meta_state: dict[str, str],
    ) -> None:
        """Extract account, creation date, and balances for report scope."""
        if tag == "Acct":
            iban = elem.findtext(".//IBAN")
            othr = elem.findtext(".//Othr/Id")
            acct = (iban if iban is not None else (othr or "")).strip()
            ccy = (elem.findtext("Ccy") or "").strip()
            meta_state["acct"] = acct
            meta_state["ccy"] = ccy
            if summary is not None:
                summary["account_id"] = acct or None
                summary["currency"] = ccy or None
        elif tag == "CreDtTm":
            if summary is not None and elem.text:
                summary["statement_date"] = elem.text.strip()[:10]
        else:
            self._handle_balance_tag(elem, summary)

    def _yield_entry_records(
        self,
        elem: etree._Element,
        meta_state: dict[str, str],
        active_summary: SummaryRecord | None,
        redact_pii: bool,
    ) -> Iterator[TransactionRecord]:
        """Yield records from an entry element and update scope summary."""
        for rec in _parse_entry_records(
            elem, meta_state["acct"], meta_state["ccy"], redact_pii
        ):
            if active_summary is not None:
                active_summary["transaction_count"] += 1
                active_summary["total_amount"] += rec["Amount"]
            yield rec
        _clear_element(elem)

    def _stream_records(
        self, redact_pii: bool = False
    ) -> Iterator[TransactionRecord]:
        """Stream transaction records via lxml iterparse with O(1) memory cleanup."""
        stream = BytesIO(self._xml_bytes)
        meta_state = {"acct": "", "ccy": ""}
        scope_summaries: list[SummaryRecord] = []
        active_summary: SummaryRecord | None = None

        context = etree.iterparse(
            stream,
            events=("start", "end"),
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            huge_tree=False,
        )

        for event, elem in context:
            if event == "start":
                elem.tag = str(etree.QName(elem).localname)
                if elem.tag == self.SCOPE_TAG:
                    meta_state["acct"] = ""
                    meta_state["ccy"] = ""
                    active_summary = _init_scope_summary()
                continue

            tag = elem.tag
            if tag in ("Acct", "CreDtTm", "Bal"):
                self._handle_metadata_event(
                    tag, elem, active_summary, meta_state
                )
            elif tag == "Ntry":
                yield from self._yield_entry_records(
                    elem, meta_state, active_summary, redact_pii
                )
            elif tag == self.SCOPE_TAG:
                if active_summary is not None:  # pragma: no branch
                    scope_summaries.append(active_summary)
                _clear_element(elem)

        self._summaries = scope_summaries

    def _handle_balance_tag(
        self, elem: etree._Element, summary: SummaryRecord | None
    ) -> None:
        """Parse opening and closing balances into scope summary record."""
        if summary is None:
            return
        code = (
            elem.findtext(".//Tp/CdOrPrtry/Cd")
            or elem.findtext(".//{*}Tp/{*}CdOrPrtry/{*}Cd")
            or ""
        )
        amt_str = elem.findtext("Amt") or elem.findtext("{*}Amt")
        if not amt_str:
            return
        amt = iso_decimal(amt_str, context="CAMT balance")
        drcr = elem.findtext("CdtDbtInd") or elem.findtext("{*}CdtDbtInd")
        signed = -amt if drcr == "DBIT" else amt
        if code in ("OPBD", "PRCD"):
            summary["opening_balance"] = signed
        elif code in ("CLBD", "CLAV"):
            summary["closing_balance"] = signed

    def parse_streaming(
        self, redact_pii: bool = False
    ) -> Iterator[TransactionRecord]:
        """Yield transaction records incrementally with O(1) memory guarantees."""
        yield from self._stream_records(redact_pii=redact_pii)

    def parse_streaming_transactions(
        self, redact_pii: bool = False
    ) -> Iterator[Transaction]:
        """Yield validated Transaction pydantic models incrementally."""
        source = self._source_name
        for rec in self.parse_streaming(redact_pii=redact_pii):
            yield _build_model(rec, source)

    def parse(self, redact_pii: bool = False) -> pd.DataFrame:
        """Parse statements into a pandas DataFrame."""
        if self._parsed_df is not None:
            return self._parsed_df
        records = list(self.parse_streaming(redact_pii=redact_pii))
        if not records:
            df = pd.DataFrame(
                columns=[
                    "Amount",
                    "Currency",
                    "DrCr",
                    "Debtor",
                    "Creditor",
                    "Reference",
                    "EndToEndId",
                    "ValDt",
                    "BookgDt",
                    "AccountId",
                ]
            )
        else:
            df = pd.DataFrame(records)
        self._parsed_df = df
        return self._parsed_df

    def get_summaries(self) -> list[SummaryRecord]:
        """Return account summaries for all scopes within the document."""
        if self._parsed_df is None:
            self.parse()
        return self._summaries or [
            {
                "account_id": None,
                "currency": None,
                "statement_date": None,
                "transaction_count": 0,
                "total_amount": Decimal("0.00"),
                "opening_balance": None,
                "closing_balance": None,
            }
        ]

    def get_summary(self) -> SummaryRecord:
        """Return single document summary or raise if multiple scopes exist."""
        return _single_summary(self.get_summaries())


class Camt052Parser(_BaseCamtStreamParser):
    """Parse ISO 20022 CAMT.052 Bank-to-Customer Account Reports."""

    SCOPE_TAG: ClassVar[str] = "Rpt"
    DOCUMENT_TAG: ClassVar[str] = "BkToCstmrAcctRpt"


class Camt054Parser(_BaseCamtStreamParser):
    """Parse ISO 20022 CAMT.054 Bank-to-Customer Debit/Credit Notifications."""

    SCOPE_TAG: ClassVar[str] = "Ntfctn"
    DOCUMENT_TAG: ClassVar[str] = "BkToCstmrDbtCdtNtfctn"
