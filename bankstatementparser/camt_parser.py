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
camt_parser.py

Provides a class CamtParser for parsing CAMT format bank statement files.
"""

import logging
import pandas as pd
from lxml import etree

# Configuring the logging
logger = logging.getLogger(__name__)


class CamtParser:
    """
    Class to parse CAMT format bank statement files.

    Attributes:
        tree (etree.Element): The Element object representing the parsed XML
        file.
        definitions (dict): Dictionary mapping balance codes to descriptions.
    """

    def __init__(self, file_name):
        """
        Initializes the parser with the given file.

        Parameters:
            file_name (str): Path to the CAMT format statement file.

        Raises:
            FileNotFoundError: If file does not exist.
            etree.XMLSyntaxError: If there is an issue parsing the XML.
        """
        try:
            # Attempt to open and read the file content
            with open(file_name, 'r', encoding='utf-8') as f:
                data = f.read()
        except FileNotFoundError:
            logger.error("File %s not found!", file_name)
            raise
        except Exception as e:
            logger.error(
                "An error occurred while reading the file: %s", str(e))
            raise

        try:
            # Remove the namespace from the XML data for easier parsing
            data = data.replace(
                ' xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"', '')
            data = bytes(data, 'utf-8')

            # Parse the XML data
            parser = etree.XMLParser(recover=True, encoding='utf-8')
            self.tree = etree.fromstring(data, parser)
        except etree.XMLSyntaxError as e:
            logger.error("XML syntax error: %s", str(e))
            raise
        except Exception as e:
            logger.error("An error occurred while parsing the XML: %s", str(e))
            raise

        # Define balance codes and their descriptions
        self.definitions = {
            'OPBD': 'Opening Booked balance',
            'CLBD': 'Closing Booked balance',
            'CLAV': 'Closing Available balance',
            'PRCD': 'Previously Closed Booked balance',
            'FWAV': 'Forward Available balance'
        }

    def get_account_balances(self):
        """
        Returns a DataFrame with balances by account.

        Returns:
            pd.DataFrame: Dataframe with columns:
                Amount, Currency, Code, Description, DrCr, Date, AccountId.
        """
        # Find all bank statements in the XML
        statements = self.tree.xpath('.//Stmt')
        balances = []

        # Iterate through each statement to gather balance information
        for statement in statements:
            # Get the balances for the current statement
            bal_list = self._get_balances_for_statement(statement)

            # Get the account ID for the current statement
            account_id = self._get_account_id(statement)

            # Add the account ID to each balance entry
            for bal in bal_list:
                bal['AccountId'] = account_id

            # Add the balances to the list
            balances.extend(bal_list)

        # Convert the list of balances to a DataFrame and return
        return pd.DataFrame(balances)

    def _get_balances_for_statement(self, statement):
        """
        Helper method to extract balances for a single statement.

        Parameters:
            statement (etree.Element): XML Element representing the statement.

        Returns:
            list: List of parsed balance dictionaries.
        """
        # Find all balance elements in the statement
        bal_elems = statement.xpath('.//Bal')
        balances = []

        # Iterate through each balance element to parse its information
        for bal_elem in bal_elems:
            balance = self._parse_balance(bal_elem)
            balances.append(balance)

        return balances

    def _parse_balance(self, bal_elem):
        """
        Parses a single Balance element.

        Parameters:
            bal_elem (etree.Element): XML Element representing the balance.

        Returns:
            dict: Parsed balance information.
        """
        # Extract and process information from the balance element
        code = bal_elem.xpath('.//Cd')[0].text
        description = self.definitions.get(code, 'Unknown code')
        amount = float(bal_elem.xpath('.//Amt')[0].text)
        cdt_dbt = bal_elem.xpath('.//CdtDbtInd')[0].text
        if cdt_dbt == 'DBIT':
            amount = -amount
        currency = bal_elem.xpath('.//Amt/@Ccy')[0]
        date = bal_elem.xpath('./Dt/Dt|./Dt/DtTm')[0].text

        # Return the balance information as a dictionary
        return {
            'Amount': amount,
            'Currency': currency,
            'Code': code,
            'Description': description,
            'DrCr': cdt_dbt,
            'Date': date
        }

    def get_transactions(self):
        """
        Returns a DataFrame with transactions by account.

        Returns:
            pd.DataFrame: Dataframe with columns:
                Amount, Currency, DrCr, Debtor, Creditor, Reference,
                ValDt, BookgDt, AccountId.
        """
        # Find all bank statements in the XML
        statements = self.tree.xpath('.//Stmt')
        transactions = []

        # Iterate through each statement to gather transaction information
        for statement in statements:
            # Get the transactions for the current statement
            tx_list = self._get_transactions_for_statement(statement)

            # Get the account ID for the current statement
            account_id = self._get_account_id(statement)

            # Add the account ID to each transaction entry
            for tx in tx_list:
                tx['AccountId'] = account_id

            # Add the transactions to the list
            transactions.extend(tx_list)

        # Convert the list of transactions to a DataFrame and return
        return pd.DataFrame(transactions)

    def _get_transactions_for_statement(self, statement):
        """
        Helper method to extract transactions for a single statement.

        Parameters:
            statement (etree.Element): XML Element representing the statement.

        Returns:
            list: List of parsed transaction dictionaries.
        """
        # Find all entry elements (transactions) in the statement
        entries = statement.xpath('./Ntry')
        transactions = []

        # Iterate through each entry to parse its information
        for entry in entries:
            tx = self._parse_transaction(entry)
            transactions.append(tx)

        return transactions

    def _parse_transaction(self, entry):
        """
        Parses a single Entry element (transaction).

        Parameters:
            entry (etree.Element): XML Element representing the entry.

        Returns:
            dict: Parsed transaction information.
        """
        # Extract and process information from the transaction entry
        debtor = self._get_element_text(entry, './/Dbtr/Nm')
        creditor = self._get_element_text(entry, './/Cdtr/Nm')

        references = [ref.text for ref in entry.xpath('.//Ustrd') if ref.text]
        reference = ''.join(references)

        amount = float(entry.xpath('./Amt')[0].text)
        currency = entry.xpath('./Amt/@Ccy')[0]
        cdt_dbt = entry.xpath('./CdtDbtInd')[0].text
        if cdt_dbt == 'DBIT':
            amount = -amount

        value_date = self._get_element_text(entry, './ValDt/Dt')
        booking_date = self._get_element_text(entry, './BookgDt/Dt')

        # Return the transaction information as a dictionary
        return {
            'Amount': amount,
            'Currency': currency,
            'DrCr': cdt_dbt,
            'Debtor': debtor,
            'Creditor': creditor,
            'Reference': reference,
            'ValDt': value_date,
            'BookgDt': booking_date
        }

    def _get_element_text(self, parent, xpath):
        """
        Helper method to safely get text content of an XML element.

        Parameters:
            parent (etree.Element): Parent XML element.
            xpath (str): XPath expression to find the child element.

        Returns:
            str: Text content of the child element if it exists, else an empty
            string.
        """
        element = parent.xpath(xpath)
        return element[0].text if element else ''

    def _get_account_id(self, statement):
        """
        Extracts the account ID from a bank statement.

        Parameters:
            statement (etree.Element): XML Element representing the bank
            statement.

        Returns:
            str: Account ID.
        """
        id_elems = statement.xpath('./Acct/Id/IBAN|./Acct/Id/Othr/Id')
        return id_elems[0].text if id_elems else ''

    def get_statement_stats(self):
        """
        Returns a DataFrame with statistics for each bank statement.

        Returns:
            pd.DataFrame: Dataframe with columns:
                AccountId, StatementCreated, NumTransactions, NetAmount.
        """
        # Find all bank statements in the XML
        statements = self.tree.xpath('.//Stmt')
        stats = []

        # Iterate through each statement to gather statistics
        for statement in statements:
            stmt_stats = self._get_statement_stats(statement)
            stats.append(stmt_stats)

        # Convert the list of statistics to a DataFrame and return
        return pd.DataFrame(stats)

    def _get_statement_stats(self, statement):
        """
        Extracts statistics for a single bank statement.

        Parameters:
            statement (etree.Element): XML Element representing the bank
            statement.

        Returns:
            dict: Statement statistics.
        """
        # Extract basic information about the statement
        account_id = self._get_account_id(statement)
        created = self._get_element_text(statement, './CreDtTm')

        # Get all transactions for the statement and calculate summary
        # statistics
        transactions = self._get_transactions_for_statement(statement)
        tx_df = pd.DataFrame(transactions)
        net_amount = tx_df['Amount'].sum() if len(tx_df) > 0 else 0

        # Return the statistics as a dictionary
        return {
            'AccountId': account_id,
            'StatementCreated': created,
            'NumTransactions': len(tx_df),
            'NetAmount': net_amount
        }

    def __repr__(self):
        """
        Returns a string representation of the parsed data.

        Returns:
            str: String representation.
        """
        return str(self.get_statement_stats())

    def camt_to_excel(self, filename):
        """
        Exports parsed CAMT data to an Excel file.

        Parameters:
            filename (str): Path to the output Excel file.
        """
        # Retrieve dataframes for balances, transactions, and statement
        # statistics
        balances = self.get_account_balances()
        transactions = self.get_transactions()
        stats = self.get_statement_stats()

        # Write the dataframes to the Excel file using the openpyxl engine
        # pylint: disable=E0110
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            balances.to_excel(writer, sheet_name='Balances', index=False)
            transactions.to_excel(
                writer, sheet_name='Transactions', index=False
            )
            stats.to_excel(writer, sheet_name='Stats', index=False)
