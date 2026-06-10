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
#
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Property-based tests using Hypothesis.

Covers:
  1. InputValidator.validate_xml_content — arbitrary string/bytes,
     encoding edge cases.
  2. CamtParser._parse_streaming_transaction — optional XML fields
     in many combinations.
  3. _parse_amount — locale-dependent number formats.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from lxml import etree

from bankstatementparser.additional_parsers import _parse_amount
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.input_validator import (
    InputValidator,
    ValidationError,
)

# -------------------------------------------------------------------
# Strategies
# -------------------------------------------------------------------

_amount_text = st.one_of(
    # Plain integer: "1234"
    st.from_regex(r"-?[0-9]{1,12}", fullmatch=True),
    # Locale-agnostic decimals: "1234.56"
    st.from_regex(r"-?[0-9]{1,12}\.[0-9]{1,4}", fullmatch=True),
    # European comma-decimal: "1234,56"
    st.from_regex(r"-?[0-9]{1,12},[0-9]{1,4}", fullmatch=True),
    # European with dot-thousands: "1.234,56"
    st.from_regex(
        r"-?[0-9]{1,3}(\.[0-9]{3})+,[0-9]{1,4}",
        fullmatch=True,
    ),
    # US with comma-thousands: "1,234.56"
    st.from_regex(
        r"-?[0-9]{1,3}(,[0-9]{3})+\.[0-9]{1,4}",
        fullmatch=True,
    ),
)

_garbage_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # no surrogates
    ),
    min_size=0,
    max_size=200,
)

_xml_safe_chars = st.characters(
    blacklist_categories=("Cs", "Cc"),  # no surrogates or control chars
)
_optional_text = st.one_of(
    st.none(),
    st.text(alphabet=_xml_safe_chars, min_size=0, max_size=50),
)


def _build_ntry_xml(
    *,
    amount: str | None = None,
    currency: str | None = None,
    cdt_dbt: str | None = None,
    debtor: str | None = None,
    creditor: str | None = None,
    reference: str | None = None,
    val_date: str | None = None,
    booking_date: str | None = None,
    debtor_addr: str | None = None,
    creditor_addr: str | None = None,
) -> etree._Element:
    """Build a minimal <Ntry> XML element with optional sub-elements."""
    root = etree.Element("Ntry")

    if amount is not None:
        amt = etree.SubElement(root, "Amt")
        amt.text = amount
        if currency is not None:
            amt.set("Ccy", currency)

    if cdt_dbt is not None:
        ind = etree.SubElement(root, "CdtDbtInd")
        ind.text = cdt_dbt

    if debtor is not None:
        dbtr = etree.SubElement(
            etree.SubElement(root, "TxDtls"), "Dbtr"
        )
        nm = etree.SubElement(dbtr, "Nm")
        nm.text = debtor
        if debtor_addr is not None:
            addr = etree.SubElement(dbtr, "PstlAdr")
            line = etree.SubElement(addr, "AdrLine")
            line.text = debtor_addr

    if creditor is not None:
        cdtr = etree.SubElement(
            root.find(".//TxDtls")
            if root.find(".//TxDtls") is not None
            else etree.SubElement(root, "TxDtls"),
            "Cdtr",
        )
        nm = etree.SubElement(cdtr, "Nm")
        nm.text = creditor
        if creditor_addr is not None:
            addr = etree.SubElement(cdtr, "PstlAdr")
            line = etree.SubElement(addr, "AdrLine")
            line.text = creditor_addr

    if reference is not None:
        rmtinf = etree.SubElement(root, "RmtInf")
        ustrd = etree.SubElement(rmtinf, "Ustrd")
        ustrd.text = reference

    if val_date is not None:
        vd = etree.SubElement(root, "ValDt")
        dt = etree.SubElement(vd, "Dt")
        dt.text = val_date

    if booking_date is not None:
        bd = etree.SubElement(root, "BookgDt")
        dt = etree.SubElement(bd, "Dt")
        dt.text = booking_date

    return root


# -------------------------------------------------------------------
# 1. _parse_amount  — locale-dependent number formats
# -------------------------------------------------------------------


class TestParseAmountProperties(unittest.TestCase):
    """Property-based tests for _parse_amount."""

    @given(text=_amount_text)
    @settings(max_examples=500)
    def test_valid_number_strings_return_decimal(
        self, text: str
    ) -> None:
        """Valid numeric strings always produce a finite Decimal."""
        result = _parse_amount(text)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, Decimal)
        self.assertTrue(result.is_finite())

    @given(value=st.one_of(st.none(), st.just(float("nan"))))
    def test_none_and_nan_return_none(self, value: Any) -> None:
        """None and NaN inputs produce None."""
        self.assertIsNone(_parse_amount(value))

    @given(text=st.just(""))
    def test_empty_string_returns_none(self, text: str) -> None:
        """Empty string returns None."""
        self.assertIsNone(_parse_amount(text))

    @given(
        text=st.text(
            alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz!@#$%^&*"),
            min_size=1,
            max_size=20,
        )
    )
    def test_pure_alpha_returns_none(self, text: str) -> None:
        """Strings with no digits return None."""
        assume(not any(c.isdigit() for c in text))
        self.assertIsNone(_parse_amount(text))

    @given(
        whole=st.integers(min_value=0, max_value=999_999_999),
        frac=st.integers(min_value=0, max_value=99),
    )
    def test_roundtrip_us_format(
        self, whole: int, frac: int
    ) -> None:
        """US format '12345.67' round-trips to the expected Decimal."""
        text = f"{whole}.{frac:02d}"
        result = _parse_amount(text)
        self.assertEqual(result, Decimal(text))

    @given(
        whole=st.integers(min_value=0, max_value=999_999),
        frac=st.integers(min_value=0, max_value=99),
    )
    def test_european_comma_decimal(
        self, whole: int, frac: int
    ) -> None:
        """European '1234,56' parses to 1234.56."""
        text = f"{whole},{frac:02d}"
        result = _parse_amount(text)
        self.assertEqual(result, Decimal(f"{whole}.{frac:02d}"))

    @given(text=_garbage_text)
    @settings(max_examples=300)
    def test_never_raises(self, text: str) -> None:
        """_parse_amount never raises — always returns Decimal or None."""
        result = _parse_amount(text)
        self.assertTrue(
            result is None or isinstance(result, Decimal)
        )


# -------------------------------------------------------------------
# 2. InputValidator.validate_xml_content
# -------------------------------------------------------------------


class TestValidateXmlContentProperties(unittest.TestCase):
    """Property-based tests for InputValidator.validate_xml_content."""

    def setUp(self) -> None:
        self.validator = InputValidator()

    @given(
        body=st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs",),
                blacklist_characters="\x00",
            ),
            min_size=1,
            max_size=200,
        )
    )
    @settings(
        max_examples=300,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_wellformed_xml_accepted(self, body: str) -> None:
        """Well-formed XML with camt namespace always accepted."""
        safe_body = (
            body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">'
            f"<Stmt>{safe_body}</Stmt>"
            "</Document>"
        )
        xml_bytes, source = self.validator.validate_xml_content(xml)
        self.assertIsInstance(xml_bytes, bytes)
        self.assertIsInstance(source, str)

    @given(
        body=st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs",),
                blacklist_characters="\x00",
            ),
            min_size=1,
            max_size=200,
        )
    )
    @settings(
        max_examples=300,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_wellformed_xml_bytes_accepted(self, body: str) -> None:
        """Well-formed XML bytes with camt namespace always accepted."""
        safe_body = (
            body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">'
            f"<Stmt>{safe_body}</Stmt>"
            "</Document>"
        )
        xml_bytes, source = self.validator.validate_xml_content(
            xml.encode("utf-8")
        )
        self.assertIsInstance(xml_bytes, bytes)

    @given(data=st.binary(min_size=0, max_size=300))
    @settings(
        max_examples=300,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_arbitrary_bytes_never_crash(self, data: bytes) -> None:
        """Arbitrary bytes either validate or raise ValidationError."""
        try:
            result = self.validator.validate_xml_content(data)
            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 2)
        except ValidationError:
            pass  # expected for most random bytes

    @given(text=_garbage_text)
    @settings(
        max_examples=300,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_arbitrary_strings_never_crash(self, text: str) -> None:
        """Arbitrary strings either validate or raise ValidationError."""
        try:
            result = self.validator.validate_xml_content(text)
            self.assertIsInstance(result, tuple)
        except ValidationError:
            pass

    def test_empty_string_rejected(self) -> None:
        """Empty string raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.validator.validate_xml_content("")

    def test_empty_bytes_rejected(self) -> None:
        """Empty bytes raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.validator.validate_xml_content(b"")

    @given(
        name=st.one_of(
            st.none(),
            st.text(min_size=0, max_size=100),
        )
    )
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_source_name_sanitized(self, name: str | None) -> None:
        """Source name is always returned as a plain string."""
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">'
            "<Stmt>x</Stmt></Document>"
        )
        _, source = self.validator.validate_xml_content(
            xml, source_name=name
        )
        self.assertIsInstance(source, str)
        # No control characters in sanitized name
        for ch in source:
            self.assertGreaterEqual(ord(ch), 32)


# -------------------------------------------------------------------
# 3. CamtParser._parse_streaming_transaction
# -------------------------------------------------------------------


class TestParseStreamingTransactionProperties(unittest.TestCase):
    """Property-based tests for CamtParser._parse_streaming_transaction."""

    def setUp(self) -> None:
        # We need a CamtParser instance but only to call the method.
        # Use from_string with a minimal valid CAMT doc.
        minimal_camt = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:'
            'camt.053.001.02">'
            "<BkToCstmrStmt><Stmt>"
            "<Id>X</Id>"
            "<Acct><Id><IBAN>DE0000</IBAN></Id></Acct>"
            "</Stmt></BkToCstmrStmt></Document>"
        )
        self.parser = CamtParser.from_string(minimal_camt)

    @given(
        amount=st.one_of(
            st.none(),
            st.floats(
                min_value=-1e12,
                max_value=1e12,
                allow_nan=False,
                allow_infinity=False,
            ).map(lambda f: f"{f:.2f}"),
        ),
        currency=st.one_of(st.none(), st.just("EUR"), st.just("USD")),
        cdt_dbt=st.one_of(st.none(), st.just("CRDT"), st.just("DBIT")),
        debtor=_optional_text,
        creditor=_optional_text,
        reference=_optional_text,
        val_date=st.one_of(st.none(), st.just("2024-01-15")),
        booking_date=st.one_of(st.none(), st.just("2024-01-16")),
        redact_pii=st.booleans(),
    )
    @settings(
        max_examples=500,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_always_returns_valid_dict(
        self,
        amount: str | None,
        currency: str | None,
        cdt_dbt: str | None,
        debtor: str | None,
        creditor: str | None,
        reference: str | None,
        val_date: str | None,
        booking_date: str | None,
        redact_pii: bool,
    ) -> None:
        """Returns a dict with required keys for any field combination."""
        elem = _build_ntry_xml(
            amount=amount,
            currency=currency,
            cdt_dbt=cdt_dbt,
            debtor=debtor,
            creditor=creditor,
            reference=reference,
            val_date=val_date,
            booking_date=booking_date,
        )
        if amount is None:
            with self.assertRaises(ValueError):
                self.parser._parse_streaming_transaction(
                    elem, "ACCT001", redact_pii=redact_pii
                )
            return
        result = self.parser._parse_streaming_transaction(
            elem, "ACCT001", redact_pii=redact_pii
        )
        self.assertIsInstance(result, dict)

        # Required keys always present
        for key in (
            "Amount",
            "Currency",
            "DrCr",
            "Debtor",
            "Creditor",
            "Reference",
            "ValDt",
            "BookgDt",
            "AccountId",
        ):
            self.assertIn(key, result)

        self.assertEqual(result["AccountId"], "ACCT001")
        self.assertIsInstance(result["Amount"], Decimal)
        self.assertTrue(result["Amount"].is_finite())

    @given(
        amount=st.floats(
            min_value=0.01,
            max_value=1e9,
            allow_nan=False,
            allow_infinity=False,
        ).map(lambda f: f"{f:.2f}"),
    )
    @settings(max_examples=200)
    def test_debit_negates_amount(self, amount: str) -> None:
        """DBIT indicator produces a negative Amount."""
        elem = _build_ntry_xml(
            amount=amount, currency="EUR", cdt_dbt="DBIT"
        )
        result = self.parser._parse_streaming_transaction(
            elem, "X"
        )
        self.assertLessEqual(result["Amount"], 0.0)

    @given(
        amount=st.floats(
            min_value=0.01,
            max_value=1e9,
            allow_nan=False,
            allow_infinity=False,
        ).map(lambda f: f"{f:.2f}"),
    )
    @settings(max_examples=200)
    def test_credit_preserves_amount(self, amount: str) -> None:
        """CRDT indicator preserves positive Amount."""
        elem = _build_ntry_xml(
            amount=amount, currency="EUR", cdt_dbt="CRDT"
        )
        result = self.parser._parse_streaming_transaction(
            elem, "X"
        )
        self.assertGreaterEqual(result["Amount"], 0.0)

    @given(
        debtor_addr=st.text(
            alphabet=_xml_safe_chars, min_size=1, max_size=50
        ),
        creditor_addr=st.text(
            alphabet=_xml_safe_chars, min_size=1, max_size=50
        ),
    )
    @settings(max_examples=200)
    def test_pii_redaction_masks_addresses(
        self, debtor_addr: str, creditor_addr: str
    ) -> None:
        """With redact_pii=True, address fields become REDACTED."""
        elem = _build_ntry_xml(
            amount="100.00",
            currency="EUR",
            cdt_dbt="CRDT",
            debtor="Alice",
            creditor="Bob",
            debtor_addr=debtor_addr,
            creditor_addr=creditor_addr,
        )
        result = self.parser._parse_streaming_transaction(
            elem, "X", redact_pii=True
        )
        if "DebtorAddress" in result:
            self.assertEqual(
                result["DebtorAddress"], "***REDACTED***"
            )
        if "CreditorAddress" in result:
            self.assertEqual(
                result["CreditorAddress"], "***REDACTED***"
            )

    def test_empty_element_raises(self) -> None:
        """Completely empty <Ntry> raises — no silent 0.0 amounts."""
        elem = etree.Element("Ntry")
        with self.assertRaises(ValueError):
            self.parser._parse_streaming_transaction(elem, "X")


if __name__ == "__main__":
    unittest.main()
