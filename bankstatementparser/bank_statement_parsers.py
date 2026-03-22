# Copyright (C) 2023 Sebastien Rousseau.
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

"""
bank_statement_parsers.py

This module provides consolidated access to bank statement parsing functionality.
The actual parser implementations are in standalone modules with compatibility wrappers.
"""

import os
from pathlib import Path
from typing import Any, Union

import pandas as pd
from lxml.etree import _Element

# Import parsers from standalone modules
from .camt_parser import CamtParser
from .input_validator import ValidationError
from .pain001_parser import Pain001Parser as StandalonePain001Parser


class FileParserError(Exception):
    """Custom exception for file parsing errors."""

    pass


class Pain001Parser:
    """
    Compatibility wrapper for SEPA Pain.001 credit transfer files.

    This maintains the original API while delegating to enhanced standalone implementation.

    Attributes:
        batches (list): List of batch elements parsed from the file.
        payments (list): List of parsed payment dictionaries.
        batches_count (int): The number of payment batches in the file.
        total_payments_count (int): The total number of payments across all batches.
    """

    def __init__(
        self, file_name: Union[str, Path], redact_pii: bool = False
    ) -> None:
        """
        Initializes the parser and parses payments from the given file.

        Parameters:
            file_name (Union[str, Path]): The path to the SEPA Pain.001 XML file.
            redact_pii (bool): Whether to redact PII data (address fields).

        Raises:
            FileNotFoundError: If the specified file cannot be found.
        """
        # Store redact_pii setting
        self._redact_pii = redact_pii

        # Delegate to the standalone parser for file I/O and XML parsing
        self._standalone_parser = StandalonePain001Parser(
            str(file_name)
        )
        tree = self._standalone_parser.tree

        # Extract payment batches from the already-parsed XML tree.
        self.batches: list[_Element] = tree.xpath(".//PmtInf")
        self.batches_count: int = len(self.batches)

        # Parse payments from each batch.
        self.payments: list[dict[str, Any]] = []
        for batch in self.batches:
            payments: list[dict[str, Any]] = self._parse_batch(batch)
            self.payments.extend(payments)

        self.total_payments_count: int = len(self.payments)

    def _parse_batch_header(self, batch: _Element) -> dict[str, str]:
        """
        Parses header data for a payment batch.

        Parameters:
            batch (_Element): The XML element representing a payment batch.

        Returns:
            Dict[str, str]: A dictionary containing header information of the batch.
        """
        # Extract relevant information from the batch header.
        execution_date: str = batch.xpath(".//ReqdExctnDt")[0].text
        debtor_name: str = batch.xpath(".//Dbtr/Nm")[0].text
        debtor_account: str = (
            batch.xpath(".//DbtrAcct/Id/IBAN|.//DbtrAcct/Id/Othr/Id")[
                0
            ].text
            if batch.xpath(".//DbtrAcct/Id/IBAN|.//DbtrAcct/Id/Othr/Id")
            else ""
        )

        return {
            "debtor_name": debtor_name,
            "debtor_account": debtor_account,
            "execution_date": execution_date,
        }

    def _parse_batch(self, batch: _Element) -> list[dict[str, Any]]:
        """
        Parses all payments in a payment batch.

        Parameters:
            batch (_Element): The XML element representing a payment batch.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a payment.
        """
        # Parse header data for the batch.
        header: dict[str, str] = self._parse_batch_header(batch)

        # Parse each payment in the batch.
        payments: list[dict[str, Any]] = []
        for payment in batch.xpath(".//CdtTrfTxInf"):
            payment_dict: dict[str, Any] = self._parse_payment(
                payment, self._redact_pii
            )
            payment_dict.update(header)
            payments.append(payment_dict)

        return payments

    def _parse_payment(
        self, payment: _Element, redact_pii: bool = False
    ) -> dict[str, Any]:
        """
        Parses a single payment within a payment batch.

        Parameters:
            payment (_Element): The XML element representing a single payment.
            redact_pii (bool): Whether to redact PII data (address fields).

        Returns:
            Dict[str, Any]: A dictionary containing information about the payment.
        """
        # Extract relevant information from the payment.
        amount: str = payment.xpath(".//InstdAmt")[0].text
        currency: str = payment.xpath(".//InstdAmt/@Ccy")[0]
        name: str = payment.xpath(".//Cdtr/Nm")[0].text
        account: str = (
            payment.xpath(".//CdtrAcct/Id/IBAN|.//CdtrAcct/Id/Othr/Id")[
                0
            ].text
            if payment.xpath(
                ".//CdtrAcct/Id/IBAN|.//CdtrAcct/Id/Othr/Id"
            )
            else ""
        )
        country: str = (
            payment.xpath(".//Ctry")[0].text
            if payment.xpath(".//Ctry")
            else ""
        )
        references: list[str] = [
            ref.text for ref in payment.xpath(".//RmtInf/Ustrd")
        ]
        reference: str = " ".join(references)
        address_lines: list[str] = [
            line.text for line in payment.xpath(".//AdrLine")
        ]
        address: str = " ".join(address_lines)

        # Apply PII redaction if requested
        if redact_pii:
            address = "***REDACTED***" if address else address

        return {
            "Name": name,
            "Amount": float(amount),
            "Currency": currency,
            "Reference": reference,
            "CreditorAccount": account,
            "Country": country,
            "Address": address,
        }

    def __repr__(self) -> str:
        """
        Returns a string representation of the Pain001Parser instance.

        Returns:
            str: A string representation of the instance.
        """
        return (
            f"Pain001Parser(batches={self.batches_count}, "
            f"payments={self.total_payments_count})"
        )


class Camt053Parser:
    """
    Compatibility wrapper for CAMT.053 bank account statement files.

    This maintains the original API while delegating to enhanced standalone implementation.

    Attributes:
        statements (list): A list of dictionaries, each representing a statement.
        transactions (list): A list of dictionaries, each representing a transaction.
    """

    # Balance type definitions.
    DEFINITIONS = {
        "OPBD": "Opening booked balance",
        "CLBD": "Closing booked balance",
        "CLAV": "Closing available balance",
    }

    def __init__(
        self, file_name: Union[str, Path], redact_pii: bool = False
    ) -> None:
        """
        Initializes the parser and parses statements and transactions from the given file.

        Parameters:
            file_name (Union[str, Path]): The path to the CAMT.053 XML file.
            redact_pii (bool): Whether to redact PII data (address fields).

        Raises:
            FileNotFoundError: If the specified file cannot be found.
            FileParserError: If the file is not a valid CAMT.053 file or if it
            does not contain any statements.
        """
        # Use the enhanced standalone parser internally
        try:
            self._parser = CamtParser(str(file_name))

            # Convert standalone parser output to original API format
            # Get data from enhanced parser
            balances_df = self._parser.get_account_balances(
                redact_pii=redact_pii
            )
            transactions_df = self._parser.get_transactions(
                redact_pii=redact_pii
            )
            stats_df = self._parser.get_statement_stats(
                redact_pii=redact_pii
            )

            # Convert to original format
            self.statements = (
                stats_df.to_dict("records")
                if not stats_df.empty
                else []
            )
            self.transactions = (
                transactions_df.to_dict("records")
                if not transactions_df.empty
                else []
            )

            # Add balance information to statements if available
            if not balances_df.empty:
                balances_by_account: dict[str, dict[str, dict[str, str]]] = {}
                for account_id, group in balances_df.groupby("AccountId"):
                    balances_by_account[account_id] = {
                        str(row["Code"]): {
                            "Amount": str(row["Amount"]),
                            "Description": str(row["Description"]),
                        }
                        for row in group.to_dict("records")
                    }

                for stmt in self.statements:
                    account_id = stmt.get("AccountId")
                    if account_id in balances_by_account:
                        stmt.update(balances_by_account[account_id])

        except ValidationError as e:
            raise FileParserError("Not a valid CAMT.053 file") from e
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"File {file_name} not found!"
            ) from e
        except Exception as e:
            raise FileParserError("Not a valid CAMT.053 file") from e

    def __repr__(self) -> str:
        """
        Returns a string representation of the Camt053Parser instance.

        Returns:
            str: A string representation of the instance.
        """
        return (
            f"Camt053Parser("
            f"statements={len(self.statements)}, "
            f"transactions={len(self.transactions)})"
        )


def process_camt053_folder(
    folder: Union[str, Path], redact_pii: bool = False
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Processes all CAMT.053 files in a specified folder.

    Parameters:
        folder (Union[str, Path]): The path to the folder containing CAMT.053 files.
        redact_pii (bool): Whether to redact PII data (address fields).

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]: A tuple containing three pandas DataFrames:
            - files_df: A DataFrame with information about the processed files.
            - statements_df: A DataFrame with parsed statement data.
            - transactions_df: A DataFrame with parsed transaction data.
    """
    files_df_list: list[dict[str, str]] = []
    statements_df: pd.DataFrame = pd.DataFrame()
    transactions_df: pd.DataFrame = pd.DataFrame()

    # Loop through each file in the specified folder.
    for file_name in os.listdir(folder):
        file_path: str = os.path.join(folder, file_name)
        if os.path.isfile(file_path):
            try:
                # Attempt to parse the file using the compatibility wrapper.
                parser: Camt053Parser = Camt053Parser(
                    file_path, redact_pii=redact_pii
                )

                # Append parsed data to the respective DataFrames.
                statement_rows: list[dict[str, Any]] = list(
                    parser.statements
                )
                statements_df = pd.concat(
                    [statements_df, pd.DataFrame(statement_rows)]
                )
                transaction_rows: list[dict[str, Any]] = list(
                    parser.transactions
                )
                transactions_df = pd.concat(
                    [transactions_df, pd.DataFrame(transaction_rows)]
                )

                # Record the successful processing of the file.
                files_df_list.append(
                    {"FileName": file_name, "Status": "Success"}
                )
            except Exception as e:
                # Record any failures along with the associated error message.
                files_df_list.append(
                    {"FileName": file_name, "Status": f"Failed: {e}"}
                )

    # Convert the list of file statuses to a DataFrame.
    files_df: pd.DataFrame = pd.DataFrame(files_df_list)
    return files_df, statements_df, transactions_df
