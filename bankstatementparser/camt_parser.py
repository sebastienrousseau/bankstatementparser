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

"""CAMT.053 bank statement parsing.

Provides :class:`CamtParser` for parsing CAMT format bank statement
files.
"""

import logging
import re
from collections.abc import Generator
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Optional, Union, cast

import pandas as pd
from lxml import etree

from ._amounts import iso_decimal
from .base_parser import BankStatementParser, _single_summary
from .exceptions import ParserError
from .input_validator import InputValidator, ValidationError
from .privacy import redact_record
from .record_types import (
    BalanceRecord,
    StatementStatsRecord,
    SummaryRecord,
    TransactionRecord,
)

# Configuring the logging
logger = logging.getLogger(__name__)

CAMT_NAMESPACE_PATTERN = re.compile(
    r'\s+xmlns="urn:iso:std:iso:20022:tech:xsd:camt\.\d{3}\.\d{3}\.\d{2}"'
)


class CamtParser(BankStatementParser):
    """Class to parse CAMT format bank statement files.

    Attributes:
        tree (etree.Element): The Element object representing the
            parsed XML file.
        definitions (dict): Dictionary mapping balance codes to descriptions.
    """

    _file_path: Optional[str]
    _source_name: str
    _source_is_memory: bool
    _xml_bytes: bytes

    def __init__(
        self,
        file_name: Union[str, Path],
        *,
        allow_recovery: bool = False,
    ) -> None:
        """Initializes the parser with the given file.

        Parameters:
            file_name (str): Path to the CAMT format statement file.
            allow_recovery (bool): If True, retry malformed XML with
                lxml's recovery parser (which silently drops broken
                content). Strict parsing is the default.

        Raises:
            FileNotFoundError: If file does not exist.
            ValidationError: If file validation fails.
            etree.XMLSyntaxError: If there is an issue parsing the XML.
        """
        super().__init__(file_name)
        self._allow_recovery = allow_recovery
        self._initialize_from_file(file_name)
        self._set_definitions()

    @classmethod
    def from_string(
        cls,
        xml_content: str,
        *,
        source_name: str = "<memory>",
        max_bytes: Optional[int] = None,
        allow_recovery: bool = False,
    ) -> "CamtParser":
        """Create a parser from an in-memory XML string."""
        return cls._from_memory(
            xml_content,
            source_name=source_name,
            max_bytes=max_bytes,
            allow_recovery=allow_recovery,
        )

    @classmethod
    def from_bytes(
        cls,
        xml_content: bytes,
        *,
        source_name: str = "<memory>",
        max_bytes: Optional[int] = None,
        allow_recovery: bool = False,
    ) -> "CamtParser":
        """Create a parser from in-memory XML bytes."""
        return cls._from_memory(
            xml_content,
            source_name=source_name,
            max_bytes=max_bytes,
            allow_recovery=allow_recovery,
        )

    @classmethod
    def _from_memory(
        cls,
        xml_content: Union[str, bytes],
        *,
        source_name: str,
        max_bytes: Optional[int],
        allow_recovery: bool = False,
    ) -> "CamtParser":
        """Internal constructor for memory-backed XML sources."""
        validator = InputValidator(max_file_size=max_bytes)
        raw_bytes, safe_source_name = validator.validate_xml_content(
            xml_content, source_name=source_name
        )

        parser = cls.__new__(cls)
        BankStatementParser.__init__(parser, safe_source_name)
        parser._original_file_name = safe_source_name
        parser._file_path = None
        parser._source_name = safe_source_name
        parser._source_is_memory = True
        parser._allow_recovery = allow_recovery
        parser._xml_bytes = parser._normalize_xml_bytes(raw_bytes)
        parser.tree = parser._parse_xml_bytes(
            parser._xml_bytes, parser._source_name
        )
        parser._set_definitions()
        return parser

    def _initialize_from_file(self, file_name: Union[str, Path]) -> None:
        """Initialize parser state from a validated filesystem path."""
        validator = InputValidator()
        validated_path: Union[str, Path] = file_name

        if isinstance(file_name, str):
            try:
                validated_path = validator.validate_input_file_path(file_name)
                logger.info("Input file validated: %s", validated_path)
            except (ValidationError, FileNotFoundError) as e:
                logger.error("File validation failed for %s: %s", file_name, e)
                raise

        self._original_file_name = file_name
        self._file_path = str(validated_path)
        self._source_name = str(validated_path)
        self._source_is_memory = False

        raw_bytes = self._read_xml_file_bytes(self._file_path)
        self._xml_bytes = self._normalize_xml_bytes(raw_bytes)
        self.tree = self._parse_xml_bytes(self._xml_bytes, self._source_name)

    def _set_definitions(self) -> None:
        """Set static balance code definitions."""
        self.definitions = {
            "OPBD": "Opening Booked balance",
            "CLBD": "Closing Booked balance",
            "CLAV": "Closing Available balance",
            "PRCD": "Previously Closed Booked balance",
            "FWAV": "Forward Available balance",
        }

    def _read_xml_file_bytes(self, file_name: str) -> bytes:
        """Read XML file bytes without exposing payload contents in errors."""
        try:
            with open(file_name, "rb") as f:
                return f.read()
        except FileNotFoundError as exc:
            logger.error("File %s not found!", file_name)
            raise FileNotFoundError(
                f"CAMT file not found: {file_name}"
            ) from exc
        except PermissionError as exc:
            logger.error("Permission denied reading file: %s", file_name)
            raise ValidationError(
                f"Permission denied reading file: {file_name}"
            ) from exc
        except OSError as e:
            logger.error(
                "An error occurred while reading the file: %s", str(e)
            )
            raise ValidationError(
                f"Error reading file {file_name}: {e!s}"
            ) from e

    def _normalize_xml_bytes(self, raw_bytes: bytes) -> bytes:
        """Normalize namespace handling while preserving UTF-8-only parsing."""
        validator = InputValidator()
        validated_bytes, _safe_source = validator.validate_xml_content(
            raw_bytes, source_name=self._source_name
        )
        data = validated_bytes.decode("utf-8")
        data = CAMT_NAMESPACE_PATTERN.sub("", data)
        return data.encode("utf-8")

    @staticmethod
    def _local_names(root: etree._Element) -> etree._Element:
        """Normalize CAMT element names independently of namespace prefixes."""
        for element in root.iter():
            if isinstance(element.tag, str):
                name = etree.QName(element)
                if name.namespace and name.namespace.startswith(
                    "urn:iso:std:iso:20022:tech:xsd:camt."
                ):
                    element.tag = name.localname
        return root

    def _parse_xml_bytes(
        self, data_bytes: bytes, source_name: str
    ) -> etree._Element:
        """Parse normalized XML bytes with hardened lxml settings."""
        try:
            strict_parser = etree.XMLParser(
                recover=False,
                encoding="utf-8",
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
                huge_tree=False,
            )
            try:
                return self._local_names(
                    etree.fromstring(data_bytes, strict_parser)
                )
            except etree.XMLSyntaxError as strict_err:
                if not getattr(self, "_allow_recovery", False):
                    raise
                error_msg = str(strict_err).lower()
                is_entity_error = any(
                    kw in error_msg
                    for kw in [
                        "entity",
                        "doctype",
                        "dtd",
                        "undefined entity",
                        "internal error",
                        "undeclared entity",
                    ]
                )
                if is_entity_error:
                    logger.warning(
                        "Strict XML parse of %s failed (%s); "
                        "retrying in recovery mode — malformed "
                        "content may be silently dropped",
                        source_name,
                        strict_err,
                    )
                    recovery_parser = etree.XMLParser(
                        recover=True,
                        encoding="utf-8",
                        resolve_entities=False,
                        load_dtd=False,
                        no_network=True,
                        huge_tree=False,
                    )
                    return self._local_names(
                        etree.fromstring(data_bytes, recovery_parser)
                    )
                raise
        except etree.XMLSyntaxError as e:
            logger.error("XML syntax error in %s: %s", source_name, str(e))
            raise
        except Exception as e:
            logger.error(
                "An error occurred while parsing XML from %s: %s",
                source_name,
                str(e),
            )
            raise

    def get_account_balances(self, redact_pii: bool = False) -> pd.DataFrame:
        """Returns a DataFrame with balances by account.

        Returns:
            pd.DataFrame: Dataframe with columns:
                Amount, Currency, Code, Description, DrCr, Date, AccountId,
                StatementIndex (zero-based document order).

        Raises:
            ValueError: If a statement contains balance-like elements but no
                properly structured Bal elements.
        """
        # Find all bank statements in the XML
        statements = self.tree.findall(".//Stmt")
        balances = []

        # Iterate through each statement to gather balance information
        for statement_index, statement in enumerate(statements):
            # Get the balances for the current statement
            bal_list = self._get_balances_for_statement(statement)

            # Validate: if statement has child elements but no proper balances
            # and no proper account structure, it may be malformed
            if not bal_list and len(statement) > 0:
                has_account = bool(statement.findall("./Acct"))
                has_entries = bool(statement.findall("./Ntry"))
                has_bal = bool(statement.findall(".//Bal"))
                # If statement has children but no standard CAMT elements,
                # it's likely a malformed structure
                if not has_account and not has_entries and not has_bal:
                    raise ValueError(
                        "Malformed CAMT statement structure: "
                        "statement contains unrecognized elements"
                    )

            # Get the account ID for the current statement
            account_id = self._get_account_id(statement)

            # Add the account ID to each balance entry
            for bal in bal_list:
                bal["AccountId"] = account_id
                bal["StatementIndex"] = statement_index

            # Add the balances to the list
            balances.extend(bal_list)

        # Convert the list of balances to a DataFrame and return
        return pd.DataFrame.from_records(
            [redact_record(row) for row in balances]
            if redact_pii
            else balances
        )

    def _get_balances_for_statement(
        self, statement: etree._Element
    ) -> list[BalanceRecord]:
        """Helper method to extract balances for a single statement.

        Parameters:
            statement (etree.Element): XML Element representing the statement.

        Returns:
            list: List of parsed balance dictionaries.
        """
        # Find all balance elements in the statement
        bal_elems = statement.findall(".//Bal")

        if not bal_elems:
            return []

        balances: list[BalanceRecord] = []

        for elem in bal_elems:
            # Safely extract required fields, skipping malformed balance elements
            code_elems = elem.findall(".//Cd")
            prtry_elems = elem.findall(".//Prtry")
            amt_elems = elem.findall(".//Amt")
            ccy_elems = elem.xpath(".//Amt/@Ccy")
            cdt_dbt_elems = elem.findall(".//CdtDbtInd")
            date_elems = elem.xpath("./Dt/Dt|./Dt/DtTm")

            if (
                not amt_elems
                or not ccy_elems
                or not cdt_dbt_elems
                or not date_elems
            ):
                logger.warning(
                    "Skipping malformed balance element: missing required fields"
                )
                continue

            # ISO 20022: Type element contains either Cd or Prtry
            if code_elems:
                code = code_elems[0].text
            elif prtry_elems:
                code = f"Proprietary: {prtry_elems[0].text}"
            else:
                logger.warning(
                    "Balance element missing both Cd and Prtry type elements, using N/A"
                )
                code = "N/A"
            amount = iso_decimal(amt_elems[0].text, context="balance element")
            currency = ccy_elems[0]
            cdt_dbt = cdt_dbt_elems[0].text
            date = date_elems[0].text
            # Apply debit sign adjustment
            if cdt_dbt == "DBIT":
                amount = -amount

            description = self.definitions.get(code, "Unknown code")

            balances.append(
                {
                    "Amount": amount,
                    "Currency": currency,
                    "Code": code,
                    "Description": description,
                    "DrCr": cdt_dbt,
                    "Date": date,
                }
            )

        return balances

    def get_transactions(self, redact_pii: bool = False) -> pd.DataFrame:
        """Returns a DataFrame with transactions by account.

        Returns:
            pd.DataFrame: Dataframe with columns:
                Amount, Currency, DrCr, Debtor, Creditor, Reference,
                ValDt, BookgDt, AccountId.
        """
        # Find all bank statements in the XML
        statements = self.tree.findall(".//Stmt")
        transactions = []

        # Iterate through each statement to gather transaction information
        for statement in statements:
            # Get the transactions for the current statement
            tx_list = self._get_transactions_for_statement(
                statement, redact_pii
            )

            # Get the account ID for the current statement
            account_id = self._get_account_id(statement)

            # Add the account ID to each transaction entry
            for tx in tx_list:
                tx["AccountId"] = account_id

            # Add the transactions to the list
            transactions.extend(tx_list)

        # Convert the list of transactions to a DataFrame and return
        return pd.DataFrame.from_records(
            [redact_record(row) for row in transactions]
            if redact_pii
            else transactions
        )

    def _get_transactions_for_statement(
        self, statement: etree._Element, redact_pii: bool = False
    ) -> list[TransactionRecord]:
        """Helper method to extract transactions for a single statement.

        Parameters:
            statement (etree.Element): XML Element representing the statement.
            redact_pii (bool): Whether to redact PII data (address fields).

        Returns:
            list: List of parsed transaction dictionaries.
        """
        # Find all entry elements (transactions) in the statement
        return self._get_transactions_for_entries(
            statement.findall("./Ntry"),
            statement.findtext("./Acct/Ccy") or "",
            redact_pii,
        )

    def _detail_amounts(
        self,
        detail: etree._Element,
        entry_amount: Decimal,
        entry_currency: str,
        batched: bool,
    ) -> tuple[Decimal, TransactionRecord]:
        """Preserve instructed values but select only account-currency booked amounts.

        One detail inherits the complete booked entry. A batch needs explicit
        per-detail values in the booked currency; conversion is never inferred.
        """
        metadata: TransactionRecord = {}
        candidates: list[Decimal] = []
        for path in (
            "./Amt",
            "./AmtDtls/TxAmt/Amt",
            "./AmtDtls/CntrValAmt/Amt",
        ):
            element = detail.find(path)
            if element is None:
                continue
            value = iso_decimal(element.text, context="transaction detail")
            currency = element.get("Ccy") or entry_currency
            if path == "./AmtDtls/CntrValAmt/Amt":
                metadata["CounterValueAmount"] = value
                metadata["CounterValueCurrency"] = currency
            else:
                metadata["TransactionAmount"] = value
                metadata["TransactionCurrency"] = currency
            if currency == entry_currency:
                candidates.append(value)
        instructed = detail.find("./AmtDtls/InstdAmt/Amt")
        if instructed is not None:
            metadata["InstructedAmount"] = iso_decimal(
                instructed.text, context="instructed amount"
            )
            metadata["InstructedCurrency"] = instructed.get("Ccy")
        if not batched:
            return entry_amount, metadata
        if not candidates:
            raise ParserError(
                "Batched transaction detail missing booked amount in entry currency"
            )
        if len(set(candidates)) != 1:
            raise ParserError("Ambiguous booked amounts in transaction detail")
        return candidates[0], metadata

    def _payment_references(
        self, element: etree._Element
    ) -> TransactionRecord:
        """Keep bank identifiers separate from remittance narratives."""
        references: TransactionRecord = {}
        end_to_end = element.findtext("./Refs/EndToEndId")
        if end_to_end:
            references["EndToEndId"] = end_to_end
        bank_reference = element.findtext(
            "./Refs/AcctSvcrRef"
        ) or element.findtext("./AcctSvcrRef")
        if bank_reference:
            references["AcctSvcrRef"] = bank_reference
        return references

    def _get_transactions_for_entries(
        self,
        entries: list[etree._Element],
        statement_currency: str,
        redact_pii: bool = False,
    ) -> list[TransactionRecord]:
        """Expand entry elements directly, without copying their XML subtrees."""
        if not entries:
            return []

        # Traverse fixed element paths directly instead of compiling XPath
        # repeatedly; extract each field once per entry or transaction detail.
        transactions: list[TransactionRecord] = []

        for entry in entries:
            # Essential transaction fields - skip entries missing required fields
            amount_elems = entry.findall("./Amt")
            cdt_dbt_elems = entry.findall("./CdtDbtInd")

            if not amount_elems:
                raise ValueError("Transaction entry missing <Amt> element")
            entry_currency = amount_elems[0].get("Ccy") or statement_currency
            if not entry_currency:
                raise ParserError("transaction entry missing currency (Ccy)")
            if not cdt_dbt_elems:
                raise ParserError("transaction entry missing CdtDbtInd")

            entry_amount = iso_decimal(
                amount_elems[0].text,
                context="transaction entry",
            )
            entry_cdt_dbt = cdt_dbt_elems[0].text
            if entry_cdt_dbt not in {"CRDT", "DBIT"}:
                raise ParserError("Invalid booked entry CdtDbtInd")

            # Dates on entry level
            val_date_elems = entry.findall("./ValDt/Dt") or entry.findall(
                "./ValDt/DtTm"
            )
            entry_val_date = val_date_elems[0].text if val_date_elems else ""

            booking_date_elems = entry.findall(
                "./BookgDt/Dt"
            ) or entry.findall("./BookgDt/DtTm")
            entry_book_date = (
                booking_date_elems[0].text if booking_date_elems else ""
            )

            tx_dtls_elems = entry.findall(".//TxDtls")
            if tx_dtls_elems:
                for tx_dtls in tx_dtls_elems:
                    amount, amount_metadata = self._detail_amounts(
                        tx_dtls,
                        entry_amount,
                        entry_currency,
                        len(tx_dtls_elems) > 1,
                    )
                    currency = entry_currency
                    cdt_dbt = tx_dtls.findtext("./CdtDbtInd") or entry_cdt_dbt
                    if cdt_dbt not in {"CRDT", "DBIT"}:
                        raise ParserError(
                            "Invalid transaction detail CdtDbtInd"
                        )
                    if len(tx_dtls_elems) == 1 and cdt_dbt != entry_cdt_dbt:
                        raise ParserError(
                            "Transaction direction conflicts with booked entry"
                        )

                    debtor_elems = (
                        tx_dtls.findall(".//Dbtr/Nm")
                        or tx_dtls.findall(".//RltdPties/Dbtr/Nm")
                        or entry.findall("./RltdPties/Dbtr/Nm")
                        or entry.findall("./Dbtr/Nm")
                    )
                    debtor = debtor_elems[0].text if debtor_elems else ""

                    creditor_elems = (
                        tx_dtls.findall(".//Cdtr/Nm")
                        or tx_dtls.findall(".//RltdPties/Cdtr/Nm")
                        or entry.findall("./RltdPties/Cdtr/Nm")
                        or entry.findall("./Cdtr/Nm")
                    )
                    creditor = creditor_elems[0].text if creditor_elems else ""

                    ref_elems = (
                        tx_dtls.findall(".//Ustrd")
                        + tx_dtls.findall(".//Strd//Ref")
                        + tx_dtls.findall(".//CdtrRefInf/Ref")
                    )
                    if not ref_elems:
                        ref_elems = (
                            entry.findall("./RmtInf/Ustrd")
                            + entry.findall("./RmtInf/Strd//Ref")
                            + entry.findall("./CdtrRefInf/Ref")
                        )
                    reference = " ".join(
                        [r.text for r in dict.fromkeys(ref_elems) if r.text]
                    )

                    tx_val_elems = tx_dtls.findall(
                        "./ValDt/Dt"
                    ) or tx_dtls.findall("./ValDt/DtTm")
                    val_date = (
                        tx_val_elems[0].text
                        if tx_val_elems
                        else entry_val_date
                    )

                    tx_book_elems = tx_dtls.findall(
                        "./BookgDt/Dt"
                    ) or tx_dtls.findall("./BookgDt/DtTm")
                    book_date = (
                        tx_book_elems[0].text
                        if tx_book_elems
                        else entry_book_date
                    )

                    debtor_addr_elems = (
                        tx_dtls.findall(".//Dbtr/PstlAdr/AdrLine")
                        or tx_dtls.findall(".//Dbtr/PstlAdr/StrtNm")
                        or entry.findall("./RltdPties/Dbtr/PstlAdr/AdrLine")
                        or entry.findall("./RltdPties/Dbtr/PstlAdr/StrtNm")
                    )
                    debtor_addr = (
                        debtor_addr_elems[0].text if debtor_addr_elems else ""
                    )

                    creditor_addr_elems = (
                        tx_dtls.findall(".//Cdtr/PstlAdr/AdrLine")
                        or tx_dtls.findall(".//Cdtr/PstlAdr/StrtNm")
                        or entry.findall("./RltdPties/Cdtr/PstlAdr/AdrLine")
                        or entry.findall("./RltdPties/Cdtr/PstlAdr/StrtNm")
                    )
                    creditor_addr = (
                        creditor_addr_elems[0].text
                        if creditor_addr_elems
                        else ""
                    )

                    if cdt_dbt == "DBIT":
                        amount = -amount

                    if redact_pii:
                        if debtor_addr:
                            debtor_addr = "***REDACTED***"
                        if creditor_addr:
                            creditor_addr = "***REDACTED***"

                    result: TransactionRecord = {
                        "Amount": amount,
                        "Currency": currency,
                        "DrCr": cdt_dbt,
                        "Debtor": debtor,
                        "Creditor": creditor,
                        "Reference": reference,
                        "ValDt": val_date,
                        "BookgDt": book_date,
                    }
                    result.update(amount_metadata)
                    result.update(self._payment_references(tx_dtls))
                    if debtor_addr:
                        result["DebtorAddress"] = debtor_addr
                    if creditor_addr:
                        result["CreditorAddress"] = creditor_addr
                    transactions.append(result)
                if len(tx_dtls_elems) > 1:
                    details = transactions[-len(tx_dtls_elems) :]
                    booked_total = (
                        -entry_amount
                        if entry_cdt_dbt == "DBIT"
                        else entry_amount
                    )
                    if (
                        any(
                            row["Currency"] != entry_currency
                            for row in details
                        )
                        or sum(
                            (row["Amount"] for row in details), Decimal("0")
                        )
                        != booked_total
                    ):
                        raise ParserError(
                            "Batched detail amounts do not conserve the booked entry total"
                        )
            else:
                # Single transaction entry without nested TxDtls
                amount = entry_amount
                currency = entry_currency
                cdt_dbt = entry_cdt_dbt

                debtor_elems = entry.findall(".//Dbtr/Nm")
                debtor = debtor_elems[0].text if debtor_elems else ""

                creditor_elems = entry.findall(".//Cdtr/Nm")
                creditor = creditor_elems[0].text if creditor_elems else ""

                ref_elems = (
                    entry.findall(".//Ustrd")
                    + entry.findall(".//Strd//Ref")
                    + entry.findall(".//CdtrRefInf/Ref")
                )
                reference = " ".join(
                    [ref.text for ref in dict.fromkeys(ref_elems) if ref.text]
                )

                debtor_addr_elems = entry.findall(
                    ".//Dbtr/PstlAdr/AdrLine"
                ) or entry.findall(".//Dbtr/PstlAdr/StrtNm")
                debtor_addr = (
                    debtor_addr_elems[0].text if debtor_addr_elems else ""
                )

                creditor_addr_elems = entry.findall(
                    ".//Cdtr/PstlAdr/AdrLine"
                ) or entry.findall(".//Cdtr/PstlAdr/StrtNm")
                creditor_addr = (
                    creditor_addr_elems[0].text if creditor_addr_elems else ""
                )

                if cdt_dbt == "DBIT":
                    amount = -amount

                if redact_pii:
                    if debtor_addr:
                        debtor_addr = "***REDACTED***"
                    if creditor_addr:
                        creditor_addr = "***REDACTED***"

                result_entry: TransactionRecord = {
                    "Amount": amount,
                    "Currency": currency,
                    "DrCr": cdt_dbt,
                    "Debtor": debtor,
                    "Creditor": creditor,
                    "Reference": reference,
                    "ValDt": entry_val_date,
                    "BookgDt": entry_book_date,
                }
                result_entry.update(self._payment_references(entry))
                if debtor_addr:
                    result_entry["DebtorAddress"] = debtor_addr
                if creditor_addr:
                    result_entry["CreditorAddress"] = creditor_addr
                transactions.append(result_entry)

        return transactions

    def _get_element_text(self, parent: etree._Element, xpath: str) -> str:
        """Helper method to safely get text content of an XML element.

        Parameters:
            parent (etree.Element): Parent XML element.
            xpath (str): XPath expression to find the child element.

        Returns:
            str: Text content of the child element if it exists, else an empty
            string.
        """
        element = parent.xpath(xpath)
        return element[0].text if element else ""

    def _get_account_id(self, statement: etree._Element) -> str:
        """Extracts the account ID from a bank statement.

        Parameters:
            statement (etree.Element): XML Element representing the bank
            statement.

        Returns:
            str: Account ID.
        """
        id_elems = statement.xpath("./Acct/Id/IBAN|./Acct/Id/Othr/Id")
        return id_elems[0].text if id_elems else ""

    def get_statement_stats(self, redact_pii: bool = False) -> pd.DataFrame:
        """Returns a DataFrame with statistics for each bank statement.

        Returns:
            pd.DataFrame: Dataframe with columns:
                AccountId, StatementCreated, NumTransactions, NetAmount.

        Raises:
            ValueError: If a transaction amount is not a valid
                ISO 20022 decimal.
        """
        # Find all bank statements in the XML
        statements = self.tree.findall(".//Stmt")
        stats = []

        # Iterate through each statement to gather statistics
        for statement in statements:
            stmt_stats = self._get_statement_stats(statement, redact_pii)
            stats.append(stmt_stats)

        # Convert the list of statistics to a DataFrame and return
        return pd.DataFrame.from_records(
            [redact_record(row) for row in stats] if redact_pii else stats
        )

    def _get_statement_stats(
        self, statement: etree._Element, redact_pii: bool = False
    ) -> StatementStatsRecord:
        """Extracts statistics for a single bank statement.

        Parameters:
            statement (etree.Element): XML Element representing the bank
            statement.
            redact_pii (bool): Whether to redact PII data (address fields).

        Returns:
            dict: Statement statistics.
        """
        # Extract basic information about the statement with batched XPath queries
        account_id = self._get_account_id(statement)

        # Batch these queries instead of calling _get_element_text multiple times
        id_elems = statement.findall("./Id")
        statement_id = id_elems[0].text if id_elems else ""

        created_elems = statement.findall("./CreDtTm")
        created = created_elems[0].text if created_elems else ""

        # Optimize: calculate transaction stats directly from XPath rather than
        # reprocessing through _get_transactions_for_statement
        entry_elems = statement.findall("./Ntry")
        num_transactions = len(entry_elems)

        # Calculate booked totals per currency, never adding incompatible units.
        scoped = self._statement_summaries(statement)
        by_currency = {
            row["currency"] or "Unknown": row["total_amount"] for row in scoped
        }
        net_amount = (
            next(iter(by_currency.values())) if len(by_currency) == 1 else None
        )

        # Return the statistics as a dictionary
        return {
            "StatementId": statement_id,
            "AccountId": account_id,
            "StatementCreated": created,
            "NumTransactions": num_transactions,
            "NetAmount": net_amount,
            "NetAmountByCurrency": by_currency,
        }

    def __repr__(self) -> str:
        """Returns a string representation of the parsed data.

        Returns:
            str: String representation.
        """
        return str(self.get_statement_stats())

    def parse(self, redact_pii: bool = False) -> pd.DataFrame:
        """Parse the CAMT file and return transaction data.

        Parameters:
            redact_pii (bool): Whether to redact PII data (address fields).

        Returns:
            pd.DataFrame: Parsed transaction data with standardized columns.
        """
        return self.get_transactions(redact_pii=redact_pii)

    def parse_streaming(
        self, redact_pii: bool = False
    ) -> Generator[TransactionRecord, None, None]:
        """Parse the CAMT file using streaming XML parsing.

        Yields transaction data incrementally to keep memory usage low
        on large files.

        Parameters:
            redact_pii (bool): Whether to redact PII data (address fields).

        Yields:
            Dict[str, Any]: Individual transaction data with standardized structure.

        Raises:
            ValueError: If a transaction entry has no parseable amount.
            ParserError: If a transaction entry has no currency and the
                enclosing statement declares none to fall back on.
        """
        source_stream = BytesIO(self._xml_bytes)

        current_account_id = ""
        current_currency = ""

        for event, elem in etree.iterparse(
            source_stream,
            events=("start", "end"),
            resolve_entities=False,
            load_dtd=False,
            no_network=True,
            huge_tree=False,
        ):
            # Start/end events are elements; comment and PI events are not requested.
            if event == "start" and elem.tag.startswith("{"):
                name = etree.QName(elem)
                if name.namespace and name.namespace.startswith(
                    "urn:iso:std:iso:20022:tech:xsd:camt."
                ):
                    elem.tag = name.localname
            if event == "start" and elem.tag == "Stmt":
                current_account_id = ""
                current_currency = ""

            elif event == "end" and elem.tag == "Acct":
                # <Acct> closes before any <Ntry> in schema order, so
                # the statement's account id and currency are available
                # to every transaction that follows. Capturing at
                # <Stmt> end would be too late: Ntry events fire first.
                id_elems = elem.xpath("./Id/IBAN|./Id/Othr/Id")
                current_account_id = id_elems[0].text or "" if id_elems else ""
                current_currency = elem.findtext("Ccy") or ""

            elif event == "end" and elem.tag == "Ntry":
                # Fail-fast on per-row parse errors — silent `continue` here
                # would drop transactions from the stream and corrupt any
                # downstream balance check. This matches PAIN.001's
                # streaming behaviour and the R-007 control documented in
                # docs/compliance/RISK_REGISTER.md.
                try:
                    # Read the bounded entry in place; keep iterparse's parent
                    # intact until its normal cleanup below.
                    for transaction_data in self._get_transactions_for_entries(
                        [elem], current_currency, redact_pii
                    ):
                        transaction_data["AccountId"] = current_account_id
                        yield (
                            cast(
                                TransactionRecord,
                                redact_record(transaction_data),
                            )
                            if redact_pii
                            else transaction_data
                        )
                except Exception as e:
                    logger.error("Error parsing transaction: %s", e)
                    raise
                finally:
                    elem.clear()
                    while elem.getprevious() is not None:
                        del elem.getparent()[0]

    def _parse_streaming_transaction(
        self,
        entry_elem: etree._Element,
        account_id: str,
        redact_pii: bool = False,
        statement_currency: str = "",
    ) -> TransactionRecord:
        """Parse a single transaction entry element for streaming mode.

        Parameters:
            entry_elem (etree.Element): XML element representing a transaction entry.
            account_id (str): Account ID for this transaction.
            redact_pii (bool): Whether to redact PII data (address fields).
            statement_currency (str): Statement-level currency used when
                the entry's <Amt> element has no Ccy attribute.

        Returns:
            Dict[str, Any]: Parsed transaction data.

        Raises:
            ValueError: If the entry has no <Amt> element or the amount
                is not a valid ISO 20022 decimal.
            ParserError: If neither the entry nor the statement carries
                a currency.
        """
        # Fast-path extraction using find/findtext instead of xpath.
        # find() uses direct tree traversal — ~5x faster than xpath().
        amt_elem = entry_elem.find("Amt")
        if amt_elem is None:
            raise ValueError("Transaction entry missing <Amt> element")
        amount = iso_decimal(amt_elem.text, context="transaction entry")
        currency = amt_elem.get("Ccy") or statement_currency
        if not currency:
            raise ParserError(
                f"transaction entry missing currency (Ccy) in {self.file_name}"
            )

        cdt_dbt_elem = entry_elem.find("CdtDbtInd")
        cdt_dbt = cdt_dbt_elem.text if cdt_dbt_elem is not None else ""

        if cdt_dbt == "DBIT":
            amount = -amount

        # Party information — single find() per field.
        debtor = ""
        creditor = ""
        reference = ""
        debtor_addr = ""
        creditor_addr = ""

        tx_dtls = entry_elem.find("NtryDtls/TxDtls")
        if tx_dtls is not None:
            dbtr = tx_dtls.find("RltdPties/Dbtr/Nm")
            if dbtr is not None:
                debtor = dbtr.text or ""
            cdtr = tx_dtls.find("RltdPties/Cdtr/Nm")
            if cdtr is not None:
                creditor = cdtr.text or ""
            ustrd = tx_dtls.find("RmtInf/Ustrd")
            if ustrd is not None and ustrd.text:
                reference = ustrd.text

            da = tx_dtls.find("RltdPties/Dbtr/PstlAdr/AdrLine")
            if da is None:
                da = tx_dtls.find("RltdPties/Dbtr/PstlAdr/StrtNm")
            if da is not None:
                debtor_addr = da.text or ""

            ca = tx_dtls.find("RltdPties/Cdtr/PstlAdr/AdrLine")
            if ca is None:
                ca = tx_dtls.find("RltdPties/Cdtr/PstlAdr/StrtNm")
            if ca is not None:
                creditor_addr = ca.text or ""

        # Fallback for CAMT dialects with Ustrd outside TxDtls
        if not reference:
            ustrd_fb = entry_elem.find(".//Ustrd")
            if ustrd_fb is not None and ustrd_fb.text:
                reference = ustrd_fb.text

        # Dates — direct child lookup
        val_date_elem = entry_elem.find("ValDt/Dt")
        if val_date_elem is None:
            val_date_elem = entry_elem.find("ValDt/DtTm")
        val_date = val_date_elem.text if val_date_elem is not None else ""

        booking_date_elem = entry_elem.find("BookgDt/Dt")
        if booking_date_elem is None:
            booking_date_elem = entry_elem.find("BookgDt/DtTm")
        booking_date = (
            booking_date_elem.text if booking_date_elem is not None else ""
        )

        # Apply PII redaction if requested
        if redact_pii:
            if debtor_addr:
                debtor_addr = "***REDACTED***"
            if creditor_addr:
                creditor_addr = "***REDACTED***"

        # Build transaction dictionary
        result: TransactionRecord = {
            "Amount": amount,
            "Currency": currency,
            "DrCr": cdt_dbt,
            "Debtor": debtor,
            "Creditor": creditor,
            "Reference": reference,
            "ValDt": val_date,
            "BookgDt": booking_date,
            "AccountId": account_id,
        }

        # Only add address fields if they exist
        if debtor_addr:
            result["DebtorAddress"] = debtor_addr
        if creditor_addr:
            result["CreditorAddress"] = creditor_addr

        return result

    def get_summaries(self, redact_pii: bool = False) -> list[SummaryRecord]:
        """Summarize each statement and currency using its own booked entries.

        Transaction counts here count booked entries, not expanded payment
        details. Balances never cross statement or currency boundaries.
        """
        summaries = [
            summary
            for statement in self.tree.findall(".//Stmt")
            for summary in self._statement_summaries(statement)
        ]
        return (
            [cast(SummaryRecord, redact_record(row)) for row in summaries]
            if redact_pii
            else summaries
        )

    def _statement_summaries(
        self, statement: etree._Element
    ) -> list[SummaryRecord]:
        """Build currency-scoped booked totals and balances for one statement."""
        account = self._get_account_id(statement)
        fallback_currency = statement.findtext("./Acct/Ccy") or "Unknown"
        groups: dict[str, SummaryRecord] = {}

        def scope(currency: str) -> SummaryRecord:
            """Create metadata once for each currency observed in the statement."""
            if currency not in groups:
                groups[currency] = {
                    "account_id": account,
                    "statement_id": statement.findtext("./Id") or "",
                    "statement_date": statement.findtext("./CreDtTm") or "",
                    "transaction_count": 0,
                    "total_amount": Decimal("0"),
                    "currency": currency,
                }
            return groups[currency]

        # Calculate booked totals directly rather than reprocessing expanded
        # transaction details, which can carry instructed foreign amounts.
        for entry in statement.findall("./Ntry"):
            amount_element = entry.find("./Amt")
            direction = entry.findtext("./CdtDbtInd")
            if amount_element is None or direction not in {"CRDT", "DBIT"}:
                raise ParserError(
                    "Summary requires booked amount and valid CdtDbtInd"
                )
            amount = iso_decimal(
                amount_element.text, context="summary booked amount"
            )
            currency = amount_element.get("Ccy") or fallback_currency
            summary = scope(currency)
            summary["transaction_count"] += 1
            summary["total_amount"] += (
                -amount if direction == "DBIT" else amount
            )

        # Add balance information only to the owning statement/currency.
        for balance in self._get_balances_for_statement(statement):
            summary = scope(balance["Currency"] or fallback_currency)
            code = balance["Code"]
            if code in {"OPBD", "CLBD"}:
                field = (
                    "opening_balance" if code == "OPBD" else "closing_balance"
                )
                if field in summary:
                    raise ParserError("Ambiguous duplicate statement balance")
                if code == "OPBD":
                    summary["opening_balance"] = balance["Amount"]
                else:
                    summary["closing_balance"] = balance["Amount"]
        if not groups:
            scope(fallback_currency)
        return list(groups.values())

    def get_summary(self, redact_pii: bool = False) -> SummaryRecord:
        """Return one statement/currency scope; use get_summaries for mixed files."""
        return _single_summary(self.get_summaries(redact_pii=redact_pii))

    def camt_to_excel(self, filename: str) -> None:
        """Exports parsed CAMT data to an Excel file.

        Parameters:
            filename (str): Path to the output Excel file.

        Raises:
            ImportError: If the optional ``openpyxl`` dependency is
                not installed.
        """
        try:
            import openpyxl  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "Excel export requires the optional 'openpyxl' "
                "dependency. Install it with: "
                "pip install 'bankstatementparser[excel]'"
            ) from exc

        # Retrieve dataframes for balances, transactions, and statement
        # statistics
        balances = self.get_account_balances()
        transactions = self.get_transactions()
        stats = self.get_statement_stats()

        # Write the dataframes to the Excel file using the openpyxl engine
        # pylint: disable=E0110
        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            balances.to_excel(writer, sheet_name="Balances", index=False)
            transactions.to_excel(
                writer, sheet_name="Transactions", index=False
            )
            stats.to_excel(writer, sheet_name="Stats", index=False)
