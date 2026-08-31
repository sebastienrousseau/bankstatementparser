# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Tests for SWIFT MT940/MT942 Field 86 structured narrative parser."""

from decimal import Decimal

from bankstatementparser.field86_parser import (
    Field86Structure,
    parse_field_86,
)


def test_parse_field_86_empty_and_none() -> None:
    """Empty or None input returns empty structure."""
    res_none = parse_field_86(None)
    assert isinstance(res_none, Field86Structure)
    assert res_none.raw_narrative == ""
    assert res_none.to_dict() == {"raw_narrative": ""}

    res_empty = parse_field_86("   ")
    assert res_empty.raw_narrative == ""


def test_parse_field_86_standard_slash_tags() -> None:
    """Standard SWIFT /TAG/value subfields are parsed correctly."""
    narrative = (
        "/EREF/E2E-998811/REMI/Invoice 2026-001/MARF/MND-4455"
        "/CDTR/ACME Corp/DBTR/Global Logistics"
        "/CDTRID/DE12ZZZ00000000001/IBAN/DE89370400440532013000"
        "/BIC/COBADEFFXXX/PURP/SALA/OCMT/EUR12500.50/CHGS/15.00/SVCR/SRV-8877"
    )
    struct = parse_field_86(narrative)
    assert struct.end_to_end_id == "E2E-998811"
    assert struct.remittance_info == "Invoice 2026-001"
    assert struct.mandate_id == "MND-4455"
    assert struct.creditor_name == "ACME Corp"
    assert struct.debtor_name == "Global Logistics"
    assert struct.creditor_id == "DE12ZZZ00000000001"
    assert struct.counterparty_iban == "DE89370400440532013000"
    assert struct.counterparty_bic == "COBADEFFXXX"
    assert struct.purpose_code == "SALA"
    assert struct.original_amount == Decimal("12500.50")
    assert struct.charges_amount == Decimal("15.00")
    assert struct.service_reference == "SRV-8877"

    d = struct.to_dict()
    assert d["original_amount"] == "12500.50"
    assert d["charges_amount"] == "15.00"
    assert d["end_to_end_id"] == "E2E-998811"


def test_parse_field_86_german_gvc_tags() -> None:
    """German SEPA GVC ?00..?63 codes are parsed into structured attributes."""
    narrative = (
        "?00116?10E2E-REF-7722?20Monthly invoice?21March 2026"
        "?30DRESDEFF700?31DE44500700100123456789?32Musterfirma GmbH?33Abteilung Finanzen"
        "?34000?60Extra Info"
    )
    struct = parse_field_86(narrative)
    assert struct.transaction_code == "116"
    assert struct.end_to_end_id == "E2E-REF-7722"
    assert struct.remittance_info == "Monthly invoice March 2026"
    assert struct.counterparty_bic == "DRESDEFF700"
    assert struct.counterparty_iban == "DE44500700100123456789"
    assert struct.creditor_name == "Musterfirma GmbH Abteilung Finanzen"
    assert struct.additional_tags is not None
    assert struct.additional_tags["?34"] == "000"
    assert struct.additional_tags["?60"] == "Extra Info"


def test_parse_field_86_fallback_iban_and_bic_regex() -> None:
    """Unstructured narrative with plain IBAN and BIC extracts them via regex."""
    narrative = (
        "Transfer to GB29NWBK60161331926819 with BIC NWBKGB2L for payroll"
    )
    struct = parse_field_86(narrative)
    assert struct.counterparty_iban == "GB29NWBK60161331926819"
    assert struct.counterparty_bic == "NWBKGB2L"
    assert struct.end_to_end_id is None


def test_parse_field_86_edge_cases_and_unknown_tags() -> None:
    """Tests unknown slash tags, invalid amounts, and NOTPROVIDED BIC."""
    narrative = (
        "/UNKNOWNTAG/ExtraData/OCMT/InvalidAmount/CHGS/InvalidFee"
        "/BIC/NOTPROVIDED/RMTINF/InvoiceDetails"
    )
    struct = parse_field_86(narrative)
    assert struct.additional_tags == {"UNKNOWNTAG": "ExtraData"}
    assert struct.original_amount is None
    assert struct.charges_amount is None
    assert struct.remittance_info == "InvoiceDetails"
    assert struct.counterparty_bic is None

    empty_gvc = "?00   ?10   "
    struct_gvc = parse_field_86(empty_gvc)
    assert struct_gvc.transaction_code is None

    empty_slash = "/EREF/   /REMI/ValidText"
    struct_slash = parse_field_86(empty_slash)
    assert struct_slash.remittance_info == "ValidText"

    multi_remi = "/REMI/Part One/REMI/Part Two"
    struct_multi = parse_field_86(multi_remi)
    assert struct_multi.remittance_info == "Part One Part Two"

    mixed_gvc_slash = "?20GvcInfo?21Continuation /REMI/SlashInfo"
    struct_mixed = parse_field_86(mixed_gvc_slash)
    assert "GvcInfo" in struct_mixed.remittance_info
