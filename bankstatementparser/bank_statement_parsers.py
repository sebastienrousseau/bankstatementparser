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

This module provides classes for parsing different types of bank statement
files.
"""

import os
import re
from lxml import etree
import pandas as pd


class FileParserError(Exception):
    """Custom exception for file parsing errors."""
    pass


class Pain001Parser:
    """
    Parser for SEPA Pain.001 credit transfer files.

    Attributes:
        batches (list): List of batch elements parsed from the file.
        payments (list): List of parsed payment dictionaries.
        batches_count (int): The number of payment batches in the file.
        total_payments_count (int): The total number of payments across all
        batches.
    """

    def __init__(self, file_name):
        """
        Initializes the parser and parses payments from the given file.

        Parameters:
            file_name (str): The path to the SEPA Pain.001 XML file.

        Raises:
            FileNotFoundError: If the specified file cannot be found.
        """
        # Attempt to open and read the file content.
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                data = f.read()
        except FileNotFoundError as e:
            raise FileNotFoundError(f"File {file_name} not found!") from e

        # Clean up the XML namespaces to simplify the XPath expressions.
        data = re.sub('<Document[\\S\\s]*?>', '<Document>', data)
        data = bytes(data, 'utf-8')

        # Parse the XML content.
        parser = etree.XMLParser(recover=True, encoding='utf-8')
        tree = etree.fromstring(data, parser)

        # Extract payment batches from the XML tree.
        self.batches = tree.xpath('.//PmtInf')
        self.batches_count = len(self.batches)

        # Parse payments from each batch.
        self.payments = []
        for batch in self.batches:
            payments = self._parse_batch(batch)
            self.payments.extend(payments)

        self.total_payments_count = len(self.payments)

    def _parse_batch_header(self, batch):
        """
        Parses header data for a payment batch.

        Parameters:
            batch (etree._Element): The XML element representing a payment
            batch.

        Returns:
            dict: A dictionary containing header information of the batch.
        """
        # Extract relevant information from the batch header.
        execution_date = batch.xpath('.//ReqdExctnDt')[0].text
        debtor_name = batch.xpath('.//Dbtr/Nm')[0].text
        debtor_account = (
            batch.xpath('.//DbtrAcct/Id/IBAN|.//DbtrAcct/Id/Othr/Id')[0].text
            if batch.xpath('.//DbtrAcct/Id/IBAN|.//DbtrAcct/Id/Othr/Id')
            else ''
        )

        return {
            'debtor_name': debtor_name,
            'debtor_account': debtor_account,
            'execution_date': execution_date
        }

    def _parse_batch(self, batch):
        """
        Parses all payments in a payment batch.

        Parameters:
            batch (etree._Element): The XML element representing a payment
            batch.

        Returns:
            list: A list of dictionaries, each representing a payment.
        """
        # Parse header data for the batch.
        header = self._parse_batch_header(batch)

        # Parse each payment in the batch.
        payments = []
        for payment in batch.xpath('.//CdtTrfTxInf'):
            payment_dict = self._parse_payment(payment)
            payment_dict.update(header)
            payments.append(payment_dict)

        return payments

    def _parse_payment(self, payment):
        """
        Parses a single payment within a payment batch.

        Parameters:
            payment (etree._Element): The XML element representing a single
            payment.

        Returns:
            dict: A dictionary containing information about the payment.
        """
        # Extract relevant information from the payment.
        amount = payment.xpath('.//InstdAmt')[0].text
        currency = payment.xpath('.//InstdAmt/@Ccy')[0]
        name = payment.xpath('.//Cdtr/Nm')[0].text
        account = (
            payment.xpath('.//CdtrAcct/Id/IBAN|.//CdtrAcct/Id/Othr/Id')[0].text
            if payment.xpath('.//CdtrAcct/Id/IBAN|.//CdtrAcct/Id/Othr/Id')
            else ''
        )
        country = (
            payment.xpath(
                './/Ctry'
            )[0].text if payment.xpath('.//Ctry') else ''
        )
        references = [ref.text for ref in payment.xpath('.//RmtInf/Ustrd')]
        reference = ' '.join(references)
        address_lines = [line.text for line in payment.xpath('.//AdrLine')]
        address = ' '.join(address_lines)

        return {
            'Name': name,
            'Amount': float(amount),
            'Currency': currency,
            'Reference': reference,
            'CreditorAccount': account,
            'Country': country,
            'Address': address
        }

    def __repr__(self):
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
    Parser for CAMT.053 bank account statement files.

    Attributes:
        statements (list): A list of dictionaries, each representing a
        statement.
        transactions (list): A list of dictionaries, each representing a
        transaction.
    """

    # Balance type definitions.
    DEFINITIONS = {
        'OPBD': 'Opening booked balance',
        'CLBD': 'Closing booked balance',
        'CLAV': 'Closing available balance'
    }

    def __init__(self, file_name):
        """
        Initializes the parser and parses statements and transactions from the
        given file.

        Parameters:
            file_name (str): The path to the CAMT.053 XML file.

        Raises:
            FileNotFoundError: If the specified file cannot be found.
            FileParserError: If the file is not a valid CAMT.053 file or if it
            does not contain any statements.
        """
        # Attempt to open and read the file content.
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                data = f.read()
        except FileNotFoundError as e:
            raise FileNotFoundError(f"File {file_name} not found!") from e

        # Clean up the XML namespaces to simplify the XPath expressions.
        data = data.replace(
            'xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"', ''
        )
        data = bytes(data, 'utf-8')

        # Parse the XML content.
        try:
            parser = etree.XMLParser(recover=True, encoding='utf-8')
            tree = etree.fromstring(data, parser)
        except Exception as e:
            raise FileParserError('Not a valid CAMT.053 file') from e

        # Extract statement elements from the XML tree.
        stmt_list = tree.xpath('.//Stmt')
        if not stmt_list:
            raise FileParserError('No statements found in the CAMT.053 file')

        # Parse statements and transactions.
        self.statements = self._parse_statements(stmt_list)
        self.transactions = self._parse_transactions(stmt_list)

    def _parse_statement_header(self, stmt):
        """
        Parses header data for a bank statement.

        Parameters:
            stmt (etree._Element): The XML element representing a bank
            statement.

        Returns:
            dict: A dictionary containing header information of the statement.
        """
        # Extract relevant information from the statement header.
        account_id = stmt.xpath('./Acct/Id/IBAN|./Acct/Id/Othr/Id')[0].text
        name = stmt.xpath(
            './Acct/Nm'
        )[0].text if stmt.xpath('./Acct/Nm') else ''
        stmt_id = stmt.xpath('./Id')[0].text

        return {
            'StatementId': stmt_id,
            'AccountId': account_id,
            'AccountName': name
        }

    def _parse_statement_balances(self, stmt):
        """
        Parses balance amounts from a bank statement.

        Parameters:
            stmt (etree._Element): The XML element representing a bank
            statement.

        Returns:
            dict: A dictionary containing balance information of the statement.
        """
        balances = {}
        for bal in stmt.xpath('.//Bal'):
            code = bal.xpath('.//Cd')[0].text
            desc = self.DEFINITIONS.get(code, 'Unknown code')
            amount = float(bal.xpath('.//Amt')[0].text)
            cdt_dbt = bal.xpath('.//CdtDbtInd')[0].text
            if cdt_dbt == 'DBIT':
                amount *= -1
            balances[code] = {
                'Amount': amount,
                'Description': desc
            }
        return balances

    def _parse_statement_summary(self, stmt):
        """
        Parses summary statistics for a bank statement.

        Parameters:
            stmt (etree._Element): The XML element representing a bank
            statement.

        Returns:
            dict: A dictionary containing summary statistics of the statement.
        """
        transactions = self._parse_transactions([stmt])
        total = sum(t['Amount'] for t in transactions)
        return {
            'NumTransactions': len(transactions),
            'TotalAmount': total
        }

    def _parse_statements(self, stmt_list):
        """
        Parses a list of bank statement elements.

        Parameters:
            stmt_list (list of etree._Element): A list of XML elements, each
            representing a bank statement.

        Returns:
            list: A list of dictionaries, each representing a bank statement.
        """
        statements = []
        for stmt in stmt_list:
            header = self._parse_statement_header(stmt)
            balances = self._parse_statement_balances(stmt)
            summary = self._parse_statement_summary(stmt)
            stmt_data = {**header, **balances, **summary}
            statements.append(stmt_data)
        return statements

    def _parse_transaction(self, entry):
        """
        Parses a single transaction entry within a bank statement.

        Parameters:
            entry (etree._Element): The XML element representing a transaction
            entry.

        Returns:
            dict: A dictionary containing information about the transaction.
        """
        # Extract relevant information from the transaction entry.
        debtor_name = entry.xpath(
            './/Dbtr/Nm'
        )[0].text if entry.xpath('.//Dbtr/Nm') else ''
        debtor_acct = entry.xpath(
            './/DbtrAcct/Id/IBAN|.//DbtrAcct/Id/Othr/Id'
        )[0].text if entry.xpath(
            './/DbtrAcct/Id/IBAN|.//DbtrAcct/Id/Othr/Id'
        ) else ''
        creditor_name = entry.xpath(
            './/Cdtr/Nm'
        )[0].text if entry.xpath('.//Cdtr/Nm') else ''
        creditor_acct = entry.xpath(
            './/CdtrAcct/Id/IBAN|.//CdtrAcct/Id/Othr/Id'
        )[0].text if entry.xpath(
            './/CdtrAcct/Id/IBAN|.//CdtrAcct/Id/Othr/Id'
        ) else ''
        amount = float(entry.xpath('./Amt')[0].text)
        currency = entry.xpath('./Amt/@Ccy')[0]
        cdt_dbt = entry.xpath('./CdtDbtInd')[0].text
        if cdt_dbt == 'DBIT':
            amount *= -1
        references = [ref.text for ref in entry.xpath('.//RmtInf/Ustrd')]
        reference = ' '.join(references)
        value_date = entry.xpath(
            './ValDt/Dt'
        )[0].text if entry.xpath(
            './ValDt/Dt'
        ) else None
        booking_date = entry.xpath(
            './BookgDt/Dt'
        )[0].text if entry.xpath('./BookgDt/Dt') else None

        return {
            'DebtorName': debtor_name,
            'DebtorAccount': debtor_acct,
            'CreditorName': creditor_name,
            'CreditorAccount': creditor_acct,
            'Amount': amount,
            'Currency': currency,
            'CreditDebit': cdt_dbt,
            'Reference': reference,
            'ValueDate': value_date,
            'BookingDate': booking_date
        }

    def _parse_transactions(self, stmt_list):
        """
        Parses all transactions from a list of bank statement elements.

        Parameters:
            stmt_list (list of etree._Element): A list of XML elements, each
            representing a bank statement.

        Returns:
            list: A list of dictionaries, each representing a transaction.
        """
        transactions = []
        for stmt in stmt_list:
            for entry in stmt.xpath('./Ntry'):
                txn = self._parse_transaction(entry)
                txn['StatementId'] = stmt.xpath('./Id')[0].text
                transactions.append(txn)
        return transactions

    def __repr__(self):
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


def process_camt053_folder(folder):
    """
    Processes all CAMT.053 files in a specified folder.

    Parameters:
        folder (str): The path to the folder containing CAMT.053 files.

    Returns:
        tuple: A tuple containing three pandas DataFrames:
            - files_df: A DataFrame with information about the processed files.
            - statements_df: A DataFrame with parsed statement data.
            - transactions_df: A DataFrame with parsed transaction data.
    """
    files_df = []
    statements_df = pd.DataFrame()
    transactions_df = pd.DataFrame()

    # Loop through each file in the specified folder.
    for file_name in os.listdir(folder):
        file_path = os.path.join(folder, file_name)
        if os.path.isfile(file_path):
            try:
                # Attempt to parse the file.
                parser = Camt053Parser(file_path)

                # Append parsed data to the respective DataFrames.
                statement_rows = [s for s in parser.statements]
                statements_df = pd.concat(
                    [statements_df, pd.DataFrame(statement_rows)]
                )
                transaction_rows = [t for t in parser.transactions]
                transactions_df = pd.concat(
                    [transactions_df, pd.DataFrame(transaction_rows)]
                )

                # Record the successful processing of the file.
                files_df.append({
                    'FileName': file_name,
                    'Status': 'Success'
                })
            except Exception as e:
                # Record any failures along with the associated error message.
                files_df.append({
                    'FileName': file_name,
                    'Status': f'Failed: {e}'
                })

    # Convert the list of file statuses to a DataFrame.
    files_df = pd.DataFrame(files_df)
    return files_df, statements_df, transactions_df
