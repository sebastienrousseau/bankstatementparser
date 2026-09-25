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

"""SEPA Pain.001 credit-transfer parsing.

Provides a class for parsing PAIN.001 format payment initiation
files.
"""

import logging
import os
import re
from collections.abc import Generator
from contextlib import ExitStack
from decimal import Decimal
from io import BytesIO
from typing import BinaryIO, Optional, Union, cast

import pandas as pd
from lxml import etree

from ._amounts import iso_decimal
from .base_parser import BankStatementParser, _single_summary
from .exceptions import Pain001ParseError
from .input_validator import InputValidator, ValidationError
from .privacy import redact_record
from .record_types import PaymentRecord, SummaryRecord

# Configuring the logging
logger = logging.getLogger(__name__)

PAIN_NAMESPACE_PATTERN = re.compile(
    r'xmlns="urn:iso:std:iso:20022:tech:xsd:pain\.\d{3}\.\d{3}\.\d{2}"'
)


class Pain001Parser(BankStatementParser):
    """Class to parse PAIN.001 format bank statement files."""

    def __init__(self, file_name: str, *, lazy: bool = False) -> None:
        """Initialize the parser with the file name.

        Args:
            file_name (str): Path to the PAIN.001 file.
            lazy (bool): Defer tree loading; streaming reads directly from disk.
                XML syntax errors are then reported during iteration.

        Raises:
            FileNotFoundError: If file does not exist.
            ValidationError: If file validation fails.
        """
        super().__init__(file_name)
        # Validate input file if it's a raw string path
        if isinstance(file_name, str):
            validator = InputValidator()
            try:
                validated_path = validator.validate_input_file_path(file_name)
                file_name = str(validated_path)
                logger.info(f"Input file validated: {file_name}")
            except ValidationError as e:
                logger.error(f"File validation failed for {file_name}: {e}")
                # Check if it's a file read error during validation and re-raise with expected message
                if "Cannot read file for format validation" in str(e):
                    raise ValidationError(
                        f"Error reading file: {str(e).split(': ')[-1]}"
                    ) from e
                raise
            except FileNotFoundError as e:
                logger.error(f"File validation failed for {file_name}: {e}")
                raise

        self.file_name = file_name
        self._stream_from_file = lazy
        self._lazy_tree = lazy
        self._tree: etree._Element | None = None
        if not lazy:
            self._load_tree()

    @property
    def tree(self) -> etree._Element:
        """Materialize the XML tree only when an eager API needs it."""
        if self._lazy_tree:
            self._load_tree()
        return self._tree

    @tree.setter
    def tree(self, value: etree._Element) -> None:
        """Keep compatibility with callers replacing the parsed tree."""
        self._tree = value
        self._lazy_tree = False

    def _load_tree(self) -> None:
        """Read and parse a file for eager access."""
        file_name = self.file_name
        try:
            # Attempt to open and read the file content
            with open(file_name, encoding="utf-8") as f:
                data = f.read()
        except FileNotFoundError as exc:
            logger.error("File %s not found!", file_name)
            raise FileNotFoundError(
                f"PAIN.001 file not found: {file_name}"
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
            raise ValidationError(f"Error reading file: {e!s}") from e

        try:
            # Remove the namespace from the XML data for easier parsing
            data_bytes = self._normalize_xml_text(data).encode("utf-8")

            # Parse the XML data with security settings
            parser = etree.XMLParser(
                recover=False,
                encoding="utf-8",
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
            )
            self.tree = etree.fromstring(data_bytes, parser)
            for element in self.tree.iter():
                self._local_name(element)
        except ValueError as e:
            logger.error("XML syntax error: %s", str(e))
            # Check if it's a basic XML structure error and use appropriate message
            error_msg = str(e)
            if "Start tag expected" in error_msg and "not found" in error_msg:
                raise ValidationError(f"Error parsing XML: {error_msg}") from e
            else:
                raise ValidationError(
                    f"Invalid XML format: {error_msg}"
                ) from e
        except etree.LxmlError as e:
            logger.error("An error occurred while parsing the XML: %s", str(e))
            error_msg = str(e)
            if "Start tag expected" in error_msg and "not found" in error_msg:
                raise ValidationError(f"Error parsing XML: {error_msg}") from e
            else:
                raise ValidationError(
                    f"Invalid XML format: {error_msg}"
                ) from e

    @staticmethod
    def _local_name(element: etree._Element) -> None:
        """Remove only PAIN namespaces, retaining foreign extension elements."""
        if isinstance(element.tag, str) and element.tag.startswith("{"):
            name = etree.QName(element)
            if name.namespace and name.namespace.startswith(
                "urn:iso:std:iso:20022:tech:xsd:pain."
            ):
                element.tag = name.localname

    def _normalize_xml_text(self, data: str) -> str:
        """Strip the default PAIN namespace for simpler XPath handling."""
        return PAIN_NAMESPACE_PATTERN.sub("", data)

    def parse(
        self,
        output_file: Optional[str] = None,
        redact_pii: bool = False,
    ) -> pd.DataFrame:
        """Parse the PAIN.001 XML file and return structured payment data.

        Extracts group header, payment information, and individual credit
        transfer transactions into a flat DataFrame.

        Args:
            output_file (str, optional): Path to save parsed data as CSV.
            redact_pii (bool): Whether to redact PII fields.

        Returns:
            pd.DataFrame: Parsed payment data with columns for header,
            payment, and transaction-level fields.

        Raises:
            ParseError: If parsing fails for any reason.
        """
        try:
            # Get the root element
            root = self.tree.getroottree().getroot()

            # Check for required PAIN.001 structure
            customer_credit_transfer = root.find(".//CstmrCdtTrfInitn")
            if customer_credit_transfer is None:
                raise ValueError(
                    "Invalid PAIN.001 structure: missing CstmrCdtTrfInitn element"
                )

            # Pre-extract header information once
            group_header = root.find(".//CstmrCdtTrfInitn/GrpHdr")
            header_fields: dict[str, Optional[str]] = {}
            if group_header is not None:
                # Batch extract all header fields in single iteration
                for child in group_header:
                    if child.tag in ["MsgId", "CreDtTm", "NbOfTxs"]:
                        header_fields[child.tag] = child.text

                # Extract initiating party
                init_party_elem = group_header.find("InitgPty/Nm")
                header_fields["InitgPty"] = (
                    init_party_elem.text
                    if init_party_elem is not None
                    else None
                )

            # Batch extract payment information records
            payment_info_records = root.findall(".//CstmrCdtTrfInitn/PmtInf")
            payments: list[dict[str, Optional[str]]] = []

            for pmt in payment_info_records:
                # Pre-extract all payment-level fields in single iteration
                pmt_fields: dict[str, Optional[str]] = {}
                for child in pmt:
                    if child.tag in [
                        "PmtInfId",
                        "PmtMtd",
                        "NbOfTxs",
                        "CtrlSum",
                        "ReqdExctnDt",
                        "ChrgBr",
                    ]:
                        pmt_fields[child.tag] = child.text
                    elif child.tag == "Dbtr":
                        # Extract debtor information
                        dbtr_name = child.find("Nm")
                        pmt_fields["DbtrNm"] = (
                            dbtr_name.text if dbtr_name is not None else None
                        )
                        # Extract debtor account
                        dbtr_acct = child.find("DbtrAcct/Id/IBAN")
                        pmt_fields["DbtrIBAN"] = (
                            dbtr_acct.text if dbtr_acct is not None else None
                        )
                    elif child.tag == "DbtrAgt":
                        # Extract debtor agent
                        dbtr_agt = child.find("FinInstnId/BIC")
                        pmt_fields["DbtrBIC"] = (
                            dbtr_agt.text if dbtr_agt is not None else None
                        )

                # Standard PAIN debtor accounts are siblings of Dbtr; retain
                # the legacy nested lookup above for older bank exports.
                debtor_account = pmt.find("DbtrAcct/Id/IBAN")
                if debtor_account is not None:
                    pmt_fields["DbtrIBAN"] = debtor_account.text

                # Batch process all transactions for this payment
                transactions = pmt.findall("CdtTrfTxInf")
                for tx in transactions:
                    payment: dict[str, Optional[str]] = (
                        pmt_fields.copy()
                    )  # Start with payment-level data

                    # Pre-extract all transaction fields in single iteration
                    for child in tx:
                        if child.tag == "PmtId":
                            end_to_end_elem = child.find("EndToEndId")
                            payment["EndToEndId"] = (
                                end_to_end_elem.text
                                if end_to_end_elem is not None
                                else None
                            )
                        elif child.tag == "Amt":
                            instd_amt_elem = child.find("InstdAmt")
                            if instd_amt_elem is not None:
                                payment["InstdAmt"] = instd_amt_elem.text
                                payment["Currency"] = instd_amt_elem.get("Ccy")
                        elif child.tag == "CdtrAgt":
                            cdtr_agt_elem = child.find("FinInstnId/BIC")
                            payment["CdtrBIC"] = (
                                cdtr_agt_elem.text
                                if cdtr_agt_elem is not None
                                else None
                            )
                        elif child.tag == "Cdtr":
                            cdtr_name_elem = child.find("Nm")
                            payment["CdtrNm"] = (
                                cdtr_name_elem.text
                                if cdtr_name_elem is not None
                                else None
                            )
                        elif child.tag == "RmtInf":
                            ustrd_elem = child.find("Ustrd")
                            payment["RmtInf"] = (
                                ustrd_elem.text
                                if ustrd_elem is not None
                                else None
                            )

                    # Add header fields to each payment record
                    payment.update(header_fields)
                    payments.append(
                        redact_record(payment) if redact_pii else payment
                    )

            # Create DataFrame from parsed data
            df = pd.DataFrame.from_records(payments)

            if output_file:
                # Use atomic write operation with temp file
                temp_file = f"{output_file}.tmp"
                df.to_csv(temp_file, index=False)
                os.replace(temp_file, output_file)
                logger.info("Parsed data saved to %s", output_file)

            return df
        except (
            OSError,
            ValueError,
            TypeError,
            etree.LxmlError,
        ) as e:
            raise Pain001ParseError(f"Error parsing PAIN.001 file: {e}") from e

    def parse_streaming(
        self, redact_pii: bool = False
    ) -> Generator[PaymentRecord, None, None]:
        """Parse the PAIN.001 file using streaming XML parsing.

        Yields payment data incrementally to keep memory usage low on
        large files.

        Parameters:
            redact_pii (bool): Whether to mask identities, identifiers and narratives.

        Yields:
            Dict[str, Any]: Individual payment transaction data.

        Raises:
            ValidationError: If the input path fails validation.
            Pain001ParseError: If the XML cannot be parsed.
        """
        # Validate input file
        if isinstance(self.file_name, str):
            validator = InputValidator()
            try:
                validated_path = validator.validate_input_file_path(
                    self.file_name
                )
                file_path = str(validated_path)
                logger.info(f"Input file validated for streaming: {file_path}")
            except (ValidationError, FileNotFoundError) as e:
                logger.error(
                    f"File validation failed for streaming {self.file_name}: {e}"
                )
                raise
        else:
            file_path = self.file_name

        # Stream-process: read in chunks, strip namespace, feed to
        # iterparse via a temporary file so we never hold the full
        # document in memory.  For files that fit comfortably in RAM
        # (< _STREAMING_MEMORY_THRESHOLD) we use BytesIO for speed.
        _STREAMING_MEMORY_THRESHOLD = 50 * 1024 * 1024  # 50 MB

        try:
            file_size = os.path.getsize(file_path)
        except FileNotFoundError as exc:
            logger.error(
                "File %s not found for streaming!",
                file_path,
            )
            raise FileNotFoundError(
                f"PAIN.001 file not found: {file_path}"
            ) from exc
        except OSError as exc:
            logger.error("Cannot stat file for streaming: %s", str(exc))
            raise ValidationError(
                f"Error reading file {file_path}: {exc}"
            ) from exc

        source_stream: Union[BytesIO, str, BinaryIO]
        temp_file: Optional[str] = None
        with ExitStack() as resources:
            try:
                if self._stream_from_file:
                    source_stream = resources.enter_context(
                        open(file_path, "rb")
                    )
                elif file_size <= _STREAMING_MEMORY_THRESHOLD:
                    # Small file — fast path via BytesIO
                    try:
                        with open(file_path, encoding="utf-8") as f:
                            data = f.read()
                    except FileNotFoundError as exc:
                        logger.error(
                            "File %s not found for streaming!",
                            file_path,
                        )
                        raise FileNotFoundError(
                            f"PAIN.001 file not found: {file_path}"
                        ) from exc
                    except PermissionError as exc:
                        logger.error(
                            "Permission denied reading file for streaming: %s",
                            file_path,
                        )
                        raise ValidationError(
                            f"Permission denied reading file: {file_path}"
                        ) from exc
                    except OSError as e:
                        logger.error(
                            "Error reading file for streaming: %s",
                            str(e),
                        )
                        raise ValidationError(
                            f"Error reading file {file_path}: {e!s}"
                        ) from e

                    data_bytes = self._normalize_xml_text(data).encode("utf-8")
                    source_stream = BytesIO(data_bytes)
                else:
                    # Large file — chunk-based namespace stripping to a
                    # temp file so peak memory stays bounded.
                    import tempfile as _tf

                    fd, temp_file = _tf.mkstemp(
                        suffix=".xml", prefix="bsp_stream_"
                    )
                    try:
                        with (
                            open(file_path, encoding="utf-8") as src,
                            os.fdopen(fd, "w", encoding="utf-8") as dst,
                        ):
                            for chunk in iter(
                                lambda: src.read(8 * 1024 * 1024), ""
                            ):
                                dst.write(
                                    PAIN_NAMESPACE_PATTERN.sub("", chunk)
                                )
                    except FileNotFoundError as exc:
                        logger.error(
                            "File %s not found for streaming!",
                            file_path,
                        )
                        raise FileNotFoundError(
                            f"PAIN.001 file not found: {file_path}"
                        ) from exc
                    except PermissionError as exc:
                        logger.error(
                            "Permission denied reading file for streaming: %s",
                            file_path,
                        )
                        raise ValidationError(
                            f"Permission denied reading file: {file_path}"
                        ) from exc
                    except OSError as e:
                        logger.error(
                            "Error reading file for streaming: %s",
                            str(e),
                        )
                        raise ValidationError(
                            f"Error reading file {file_path}: {e!s}"
                        ) from e

                    source_stream = temp_file

                # Track context for header and payment info
                header_fields: dict[str, Optional[str]] = {}
                current_payment_info: dict[str, Optional[str]] = {}

                for event, elem in etree.iterparse(
                    source_stream,
                    events=("start", "end"),
                    resolve_entities=False,
                    load_dtd=False,
                    no_network=True,
                    huge_tree=False,
                    encoding="utf-8",
                ):
                    if event == "start":
                        self._local_name(elem)
                    if event == "end" and elem.tag == "GrpHdr":
                        header_fields = {"InitgPty": None}
                        for child in elem:
                            if child.tag in [
                                "MsgId",
                                "CreDtTm",
                                "NbOfTxs",
                            ]:
                                header_fields[child.tag] = child.text
                            elif child.tag == "InitgPty":
                                nm_elem = child.find("Nm")
                                header_fields["InitgPty"] = (
                                    nm_elem.text
                                    if nm_elem is not None
                                    else None
                                )
                        elem.clear()

                    elif event == "start" and elem.tag == "PmtInf":
                        current_payment_info = {}

                    elif event == "end" and elem.tag in (
                        "PmtInfId",
                        "PmtMtd",
                        "NbOfTxs",
                        "CtrlSum",
                        "ReqdExctnDt",
                        "ChrgBr",
                    ):
                        parent = elem.getparent()
                        if parent is not None and parent.tag == "PmtInf":
                            current_payment_info[elem.tag] = elem.text

                    elif event == "end" and elem.tag == "Dbtr":
                        parent = elem.getparent()
                        if parent is not None and parent.tag == "PmtInf":
                            dbtr_name = elem.find("Nm")
                            current_payment_info["DbtrNm"] = (
                                dbtr_name.text
                                if dbtr_name is not None
                                else None
                            )

                    elif event == "end" and elem.tag == "DbtrAcct":
                        parent = elem.getparent()
                        if parent is not None and parent.tag == "PmtInf":
                            iban = elem.find("Id/IBAN")
                            current_payment_info["DbtrIBAN"] = (
                                iban.text if iban is not None else None
                            )

                    elif event == "end" and elem.tag == "DbtrAgt":
                        parent = elem.getparent()
                        if parent is not None and parent.tag == "PmtInf":
                            bic = elem.find("FinInstnId/BIC")
                            current_payment_info["DbtrBIC"] = (
                                bic.text if bic is not None else None
                            )

                    elif event == "end" and elem.tag == "CdtTrfTxInf":
                        try:
                            payment_data = self._parse_streaming_payment(
                                elem,
                                current_payment_info,
                                header_fields,
                                redact_pii,
                            )
                            yield payment_data
                        except Exception as e:
                            logger.error(
                                "Error parsing payment transaction: %s",
                                e,
                            )
                            raise
                        finally:
                            elem.clear()
                            while elem.getprevious() is not None:
                                del elem.getparent()[0]
                    elif event == "end" and elem.tag == "PmtInf":
                        elem.clear()
                        while elem.getprevious() is not None:
                            del elem.getparent()[0]
            finally:
                if temp_file is not None:
                    try:
                        os.unlink(temp_file)
                    except OSError as exc:
                        logger.debug(
                            "Could not remove temp file %s: %s",
                            temp_file,
                            exc,
                        )

    def _parse_streaming_payment(
        self,
        tx_elem: etree._Element,
        payment_info: dict[str, Optional[str]],
        header_fields: dict[str, Optional[str]],
        redact_pii: bool = False,
    ) -> PaymentRecord:
        """Parse a single credit transfer transaction element for streaming mode.

        Parameters:
            tx_elem (etree.Element): XML element representing a credit transfer transaction.
            payment_info (Dict[str, Any]): Payment-level information.
            header_fields (Dict[str, Any]): Header-level information.
            redact_pii (bool): Whether to mask identities, identifiers and narratives.

        Returns:
            Dict[str, Any]: Parsed payment data.
        """
        # Start with payment-level data
        payment: dict[str, Optional[str]] = payment_info.copy()

        # Extract transaction-specific fields
        for child in tx_elem:
            if child.tag == "PmtId":
                end_to_end_elem = child.find("EndToEndId")
                payment["EndToEndId"] = (
                    end_to_end_elem.text
                    if end_to_end_elem is not None
                    else None
                )
            elif child.tag == "Amt":
                instd_amt_elem = child.find("InstdAmt")
                if instd_amt_elem is not None:
                    payment["InstdAmt"] = instd_amt_elem.text
                    payment["Currency"] = instd_amt_elem.get("Ccy")
            elif child.tag == "CdtrAgt":
                cdtr_agt_elem = child.find("FinInstnId/BIC")
                payment["CdtrBIC"] = (
                    cdtr_agt_elem.text if cdtr_agt_elem is not None else None
                )
            elif child.tag == "Cdtr":
                cdtr_name_elem = child.find("Nm")
                payment["CdtrNm"] = (
                    cdtr_name_elem.text if cdtr_name_elem is not None else None
                )
            elif child.tag == "RmtInf":
                ustrd_elem = child.find("Ustrd")
                payment["RmtInf"] = (
                    ustrd_elem.text if ustrd_elem is not None else None
                )

        # Add header fields
        payment.update(header_fields)

        # Apply PII redaction if requested
        if redact_pii:
            payment = redact_record(payment)

        return cast(PaymentRecord, payment)

    def get_summaries(self, redact_pii: bool = False) -> list[SummaryRecord]:
        """Get a summary of the parsed PAIN.001 statement data.

        Returns:
            Dict[str, Any]: Summary information including message details,
            transaction counts, and total amounts.
        """
        try:
            # Get the root element
            root = self.tree.getroottree().getroot()

            # Get the group header and batch extract all fields
            group_header = root.find(".//CstmrCdtTrfInitn/GrpHdr")
            header_data = {
                "MsgId": "Unknown",
                "CreDtTm": "Unknown",
                "NbOfTxs": "0",
                "InitgPty": "Unknown",
            }

            if group_header is not None:
                # Batch extract all header fields in one iteration
                for child in group_header:
                    if child.tag in ["MsgId", "CreDtTm", "NbOfTxs"]:
                        header_data[child.tag] = (
                            child.text if child.text else "Unknown"
                        )
                    elif child.tag == "InitgPty":
                        nm_elem = child.find("Nm")
                        header_data["InitgPty"] = (
                            nm_elem.text
                            if nm_elem is not None and nm_elem.text
                            else "Unknown"
                        )

            # Batch extract all payment information and calculate totals
            payment_info_records = root.findall(".//CstmrCdtTrfInitn/PmtInf")
            groups: dict[tuple[str, str], SummaryRecord] = {}

            for pmt in payment_info_records:
                account = (
                    pmt.findtext("./DbtrAcct/Id/IBAN")
                    or pmt.findtext("./Dbtr/DbtrAcct/Id/IBAN")
                    or "Unknown"
                )
                # Pre-extract all transactions for this payment in one call
                transactions = pmt.findall("CdtTrfTxInf")
                for tx in transactions:
                    # Find amount element directly rather than using nested XPath
                    amt_elem = None
                    for child in tx:
                        if child.tag == "Amt":
                            amt_elem = child.find("InstdAmt")
                            break

                    if amt_elem is None or not amt_elem.text:
                        raise Pain001ParseError(
                            "Summary requires every payment amount"
                        )
                    currency = amt_elem.get("Ccy", "Unknown")
                    key = (account, currency)
                    if key not in groups:
                        groups[key] = {
                            "account_id": account,
                            "statement_date": header_data["CreDtTm"],
                            "transaction_count": 0,
                            "total_amount": Decimal("0"),
                            "currency": currency,
                            "message_id": header_data["MsgId"],
                            "initiating_party": header_data["InitgPty"],
                        }
                    summary = groups[key]
                    summary["transaction_count"] += 1
                    summary["total_amount"] += iso_decimal(
                        amt_elem.text, context="InstdAmt element"
                    )

            summaries = list(groups.values()) or [
                {
                    "account_id": "Unknown",
                    "statement_date": header_data["CreDtTm"],
                    "transaction_count": 0,
                    "total_amount": Decimal("0"),
                    "currency": "Unknown",
                    "message_id": header_data["MsgId"],
                    "initiating_party": header_data["InitgPty"],
                }
            ]
            return (
                [cast(SummaryRecord, redact_record(row)) for row in summaries]
                if redact_pii
                else summaries
            )
        except Exception as e:
            raise Pain001ParseError(
                f"cannot summarise {self.file_name}: {e}"
            ) from e

    def get_summary(self, redact_pii: bool = False) -> SummaryRecord:
        """Return one account/currency scope; reject totals spanning scopes."""
        return _single_summary(self.get_summaries(redact_pii=redact_pii))
