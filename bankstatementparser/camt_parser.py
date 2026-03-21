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
import os
import re
import tempfile
from typing import Dict, List, Optional, Union, Any, Generator
import pandas as pd
from lxml import etree
from pathlib import Path
from .base_parser import BankStatementParser
from .input_validator import InputValidator, ValidationError

# Configuring the logging
logger = logging.getLogger(__name__)


class CamtParser(BankStatementParser):
    """
    Class to parse CAMT format bank statement files.

    Attributes:
        tree (etree.Element): The Element object representing the parsed XML
        file.
        definitions (dict): Dictionary mapping balance codes to descriptions.
    """

    def __init__(self, file_name: str) -> None:
        """
        Initializes the parser with the given file.

        Parameters:
            file_name (str): Path to the CAMT format statement file.

        Raises:
            FileNotFoundError: If file does not exist.
            ValidationError: If file validation fails.
            etree.XMLSyntaxError: If there is an issue parsing the XML.
        """
        super().__init__(file_name)

        # Store original file name and validate input file if it's a raw string path
        self._original_file_name = file_name
        if isinstance(file_name, str):
            validator = InputValidator()
            try:
                validated_path = validator.validate_input_file_path(file_name)
                file_name = str(validated_path)
                logger.info(f"Input file validated: {file_name}")
            except (ValidationError, FileNotFoundError) as e:
                logger.error(f"File validation failed for {file_name}: {e}")
                raise

        # Store the validated file path
        self._file_path = file_name

        try:
            # Attempt to open and read the file content
            with open(file_name, 'r', encoding='utf-8') as f:
                data = f.read()
        except FileNotFoundError:
            logger.error("File %s not found!", file_name)
            raise FileNotFoundError(f"CAMT file not found: {file_name}")
        except PermissionError:
            logger.error("Permission denied reading file: %s", file_name)
            raise ValidationError(f"Permission denied reading file: {file_name}")
        except Exception as e:
            logger.error(
                "An error occurred while reading the file: %s", str(e))
            raise ValidationError(f"Error reading file {file_name}: {str(e)}")

        try:
            # Remove the namespace from the XML data for easier parsing
            data = re.sub(
                r'\s+xmlns="urn:iso:std:iso:20022:tech:xsd:camt\.\d{3}\.\d{3}\.\d{2}"', '', data)
            data_bytes = bytes(data, 'utf-8')

            # First try strict parsing to validate XML structure
            strict_parser = etree.XMLParser(
                recover=False,
                encoding='utf-8',
                resolve_entities=False,
                load_dtd=False,
                no_network=True
            )
            try:
                self.tree = etree.fromstring(data_bytes, strict_parser)
            except etree.XMLSyntaxError as strict_err:
                # If strict parsing fails, check if it's due to DTD/entity issues
                # which are expected with our security settings (resolve_entities=False)
                error_msg = str(strict_err).lower()
                is_entity_error = any(kw in error_msg for kw in [
                    'entity', 'doctype', 'dtd', 'undefined entity',
                    'internal error', 'undeclared entity'
                ])
                if is_entity_error:
                    # Fall back to recovery parser for entity-related issues
                    recovery_parser = etree.XMLParser(
                        recover=True,
                        encoding='utf-8',
                        resolve_entities=False,
                        load_dtd=False,
                        no_network=True
                    )
                    self.tree = etree.fromstring(data_bytes, recovery_parser)
                else:
                    # For structural XML errors, raise the error
                    raise
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

    def get_account_balances(self, redact_pii: bool = False) -> pd.DataFrame:
        """
        Returns a DataFrame with balances by account.

        Returns:
            pd.DataFrame: Dataframe with columns:
                Amount, Currency, Code, Description, DrCr, Date, AccountId.

        Raises:
            ValueError: If a statement contains balance-like elements but no
                properly structured Bal elements.
        """
        # Find all bank statements in the XML
        statements = self.tree.xpath('.//Stmt')
        balances = []

        # Iterate through each statement to gather balance information
        for statement in statements:
            # Get the balances for the current statement
            bal_list = self._get_balances_for_statement(statement)

            # Validate: if statement has child elements but no proper balances
            # and no proper account structure, it may be malformed
            if not bal_list and len(statement) > 0:
                has_account = bool(statement.xpath('./Acct'))
                has_entries = bool(statement.xpath('./Ntry'))
                has_bal = bool(statement.xpath('.//Bal'))
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
                bal['AccountId'] = account_id

            # Add the balances to the list
            balances.extend(bal_list)

        # Convert the list of balances to a DataFrame and return
        return pd.DataFrame(balances)

    def _get_balances_for_statement(self, statement: etree._Element) -> List[Dict[str, Any]]:
        """
        Helper method to extract balances for a single statement.

        Parameters:
            statement (etree.Element): XML Element representing the statement.

        Returns:
            list: List of parsed balance dictionaries.
        """
        # Find all balance elements in the statement
        bal_elems = statement.xpath('.//Bal')

        if not bal_elems:
            return []

        balances = []

        for elem in bal_elems:
            # Safely extract required fields, skipping malformed balance elements
            code_elems = elem.xpath('.//Cd')
            prtry_elems = elem.xpath('.//Prtry')
            amt_elems = elem.xpath('.//Amt')
            ccy_elems = elem.xpath('.//Amt/@Ccy')
            cdt_dbt_elems = elem.xpath('.//CdtDbtInd')
            date_elems = elem.xpath('./Dt/Dt|./Dt/DtTm')

            if not amt_elems or not ccy_elems or not cdt_dbt_elems or not date_elems:
                logger.warning("Skipping malformed balance element: missing required fields")
                continue

            # ISO 20022: Type element contains either Cd or Prtry
            if code_elems:
                code = code_elems[0].text
            elif prtry_elems:
                code = f"Proprietary: {prtry_elems[0].text}"
            else:
                logger.warning("Balance element missing both Cd and Prtry type elements, using N/A")
                code = "N/A"
            amount = float(amt_elems[0].text)
            currency = ccy_elems[0]
            cdt_dbt = cdt_dbt_elems[0].text
            date = date_elems[0].text
            # Apply debit sign adjustment
            if cdt_dbt == 'DBIT':
                amount = -amount

            description = self.definitions.get(code, 'Unknown code')

            balances.append({
                'Amount': amount,
                'Currency': currency,
                'Code': code,
                'Description': description,
                'DrCr': cdt_dbt,
                'Date': date
            })

        return balances


    def get_transactions(self, redact_pii: bool = False) -> pd.DataFrame:
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
            tx_list = self._get_transactions_for_statement(statement, redact_pii)

            # Get the account ID for the current statement
            account_id = self._get_account_id(statement)

            # Add the account ID to each transaction entry
            for tx in tx_list:
                tx['AccountId'] = account_id

            # Add the transactions to the list
            transactions.extend(tx_list)

        # Convert the list of transactions to a DataFrame and return
        return pd.DataFrame(transactions)

    def _get_transactions_for_statement(self, statement: etree._Element, redact_pii: bool = False) -> List[Dict[str, Any]]:
        """
        Helper method to extract transactions for a single statement.

        Parameters:
            statement (etree.Element): XML Element representing the statement.
            redact_pii (bool): Whether to redact PII data (address fields).

        Returns:
            list: List of parsed transaction dictionaries.
        """
        # Find all entry elements (transactions) in the statement
        entries = statement.xpath('./Ntry')

        if not entries:
            return []

        # Batch XPath queries to eliminate N+1 pattern
        # Pre-extract all data with single queries per field type
        amounts = []
        currencies = []
        cdt_dbt_inds = []
        debtors = []
        creditors = []
        references = []
        value_dates = []
        booking_dates = []
        debtor_addresses = []
        creditor_addresses = []

        for entry in entries:
            # Essential transaction fields - skip entries missing required fields
            amount_elems = entry.xpath('./Amt')
            currency_elems = entry.xpath('./Amt/@Ccy')
            cdt_dbt_elems = entry.xpath('./CdtDbtInd')

            if not amount_elems or not currency_elems or not cdt_dbt_elems:
                logger.warning("Skipping malformed transaction entry: missing required fields")
                continue

            amounts.append(float(amount_elems[0].text))
            currencies.append(currency_elems[0])
            cdt_dbt_inds.append(cdt_dbt_elems[0].text)

            # Party information
            debtor_elems = entry.xpath('.//Dbtr/Nm')
            debtors.append(debtor_elems[0].text if debtor_elems else '')

            creditor_elems = entry.xpath('.//Cdtr/Nm')
            creditors.append(creditor_elems[0].text if creditor_elems else '')

            # References
            ref_elems = entry.xpath('.//Ustrd')
            references.append(''.join([ref.text for ref in ref_elems if ref.text]))

            # Dates
            val_date_elems = entry.xpath('./ValDt/Dt')
            if not val_date_elems:
                val_date_elems = entry.xpath('./ValDt/DtTm')
            value_dates.append(val_date_elems[0].text if val_date_elems else '')

            booking_date_elems = entry.xpath('./BookgDt/Dt')
            if not booking_date_elems:
                booking_date_elems = entry.xpath('./BookgDt/DtTm')
            booking_dates.append(booking_date_elems[0].text if booking_date_elems else '')

            # Address information
            debtor_addr_elems = entry.xpath('.//Dbtr/PstlAdr/AdrLine')
            if not debtor_addr_elems:
                debtor_addr_elems = entry.xpath('.//Dbtr/PstlAdr/StrtNm')
            debtor_addr = debtor_addr_elems[0].text if debtor_addr_elems else ''
            debtor_addresses.append(debtor_addr)

            creditor_addr_elems = entry.xpath('.//Cdtr/PstlAdr/AdrLine')
            if not creditor_addr_elems:
                creditor_addr_elems = entry.xpath('.//Cdtr/PstlAdr/StrtNm')
            creditor_addr = creditor_addr_elems[0].text if creditor_addr_elems else ''
            creditor_addresses.append(creditor_addr)

        transactions = []

        # Reconstruct transactions from batched data
        for i, (amount, currency, cdt_dbt, debtor, creditor, reference, val_date, book_date, debtor_addr, creditor_addr) in enumerate(
            zip(amounts, currencies, cdt_dbt_inds, debtors, creditors, references, value_dates, booking_dates, debtor_addresses, creditor_addresses)
        ):
            # Apply debit sign adjustment
            if cdt_dbt == 'DBIT':
                amount = -amount

            # Apply PII redaction if requested
            if redact_pii:
                if debtor_addr:
                    debtor_addr = '***REDACTED***'
                if creditor_addr:
                    creditor_addr = '***REDACTED***'

            # Build transaction dictionary
            result = {
                'Amount': amount,
                'Currency': currency,
                'DrCr': cdt_dbt,
                'Debtor': debtor,
                'Creditor': creditor,
                'Reference': reference,
                'ValDt': val_date,
                'BookgDt': book_date
            }

            # Only add address fields if they exist
            if debtor_addr:
                result['DebtorAddress'] = debtor_addr
            if creditor_addr:
                result['CreditorAddress'] = creditor_addr

            transactions.append(result)

        return transactions


    def _get_element_text(self, parent: etree._Element, xpath: str) -> str:
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

    def _get_account_id(self, statement: etree._Element) -> str:
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

    def get_statement_stats(self, redact_pii: bool = False) -> pd.DataFrame:
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
            stmt_stats = self._get_statement_stats(statement, redact_pii)
            stats.append(stmt_stats)

        # Convert the list of statistics to a DataFrame and return
        return pd.DataFrame(stats)

    def _get_statement_stats(self, statement: etree._Element, redact_pii: bool = False) -> Dict[str, Any]:
        """
        Extracts statistics for a single bank statement.

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
        id_elems = statement.xpath('./Id')
        statement_id = id_elems[0].text if id_elems else ''

        created_elems = statement.xpath('./CreDtTm')
        created = created_elems[0].text if created_elems else ''

        # Optimize: calculate transaction stats directly from XPath rather than
        # reprocessing through _get_transactions_for_statement
        entry_elems = statement.xpath('./Ntry')
        num_transactions = len(entry_elems)

        # Calculate net amount directly without full transaction parsing
        net_amount = 0.0
        if entry_elems:
            for entry in entry_elems:
                amount_elems = entry.xpath('./Amt')
                cdt_dbt_elems = entry.xpath('./CdtDbtInd')

                if amount_elems and cdt_dbt_elems:
                    amount = float(amount_elems[0].text)
                    if cdt_dbt_elems[0].text == 'DBIT':
                        amount = -amount
                    net_amount += amount

        # Return the statistics as a dictionary
        return {
            'StatementId': statement_id,
            'AccountId': account_id,
            'StatementCreated': created,
            'NumTransactions': num_transactions,
            'NetAmount': net_amount
        }

    def __repr__(self) -> str:
        """
        Returns a string representation of the parsed data.

        Returns:
            str: String representation.
        """
        return str(self.get_statement_stats())

    def parse(self, redact_pii: bool = False) -> pd.DataFrame:
        """
        Parse the CAMT file and return transaction data.

        Parameters:
            redact_pii (bool): Whether to redact PII data (address fields).

        Returns:
            pd.DataFrame: Parsed transaction data with standardized columns.
        """
        return self.get_transactions(redact_pii=redact_pii)

    def parse_streaming(self, redact_pii: bool = False) -> Generator[Dict[str, Any], None, None]:
        """
        Parse the CAMT file using streaming XML parsing for large files.
        Yields transaction data incrementally to keep memory usage low.

        Parameters:
            redact_pii (bool): Whether to redact PII data (address fields).

        Yields:
            Dict[str, Any]: Individual transaction data with standardized structure.
        """
        # Get the validated file path
        file_path = self._file_path

        try:
            # Read file content for namespace removal
            with open(file_path, 'r', encoding='utf-8') as f:
                data = f.read()
        except FileNotFoundError:
            logger.error("File %s not found for streaming!", file_path)
            raise FileNotFoundError(f"CAMT file not found: {file_path}")
        except PermissionError:
            logger.error("Permission denied reading file for streaming: %s", file_path)
            raise ValidationError(f"Permission denied reading file: {file_path}")
        except Exception as e:
            logger.error("Error reading file for streaming: %s", str(e))
            raise ValidationError(f"Error reading file {file_path}: {str(e)}")

        # Remove namespace and write to temp file for streaming
        data = re.sub(
            r'\s+xmlns="urn:iso:std:iso:20022:tech:xsd:camt\.\d{3}\.\d{3}\.\d{2}"', '', data)

        fd, temp_file = tempfile.mkstemp(suffix='.xml', prefix='bsp_streaming_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(data)

            # Set up iterative XML parser with security settings
            parser = etree.XMLParser(
                recover=False,
                encoding='utf-8',
                resolve_entities=False,
                load_dtd=False,
                no_network=True
            )

            # Track statement context for account ID mapping
            current_statement = None
            current_account_id = ''

            # Use iterparse to process elements incrementally
            for event, elem in etree.iterparse(temp_file, events=('start', 'end')):

                if event == 'start' and elem.tag == 'Stmt':
                    # Started a new statement, extract account ID
                    current_statement = elem

                elif event == 'end' and elem.tag == 'Stmt' and current_statement is not None:
                    # Extract account ID from completed statement
                    id_elems = current_statement.xpath('./Acct/Id/IBAN|./Acct/Id/Othr/Id')
                    current_account_id = id_elems[0].text if id_elems else ''
                    current_statement = None

                elif event == 'end' and elem.tag == 'Ntry':
                    # Process completed transaction entry
                    try:
                        transaction_data = self._parse_streaming_transaction(elem, current_account_id, redact_pii)
                        yield transaction_data
                    except Exception as e:
                        logger.warning(f"Error parsing transaction: {e}")
                        # Continue processing other transactions
                        continue
                    finally:
                        # Clear the element and its parent references to free memory
                        elem.clear()
                        # Also clear parent references if element has parent
                        while elem.getprevious() is not None:
                            del elem.getparent()[0]

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file)
            except OSError:
                pass  # Ignore if temp file cleanup fails

    def _parse_streaming_transaction(self, entry_elem: etree._Element, account_id: str, redact_pii: bool = False) -> Dict[str, Any]:
        """
        Parse a single transaction entry element for streaming mode.

        Parameters:
            entry_elem (etree.Element): XML element representing a transaction entry.
            account_id (str): Account ID for this transaction.
            redact_pii (bool): Whether to redact PII data (address fields).

        Returns:
            Dict[str, Any]: Parsed transaction data.
        """
        # Extract essential transaction fields
        amount_elems = entry_elem.xpath('./Amt')
        amount = float(amount_elems[0].text) if amount_elems else 0.0

        currency_elems = entry_elem.xpath('./Amt/@Ccy')
        currency = currency_elems[0] if currency_elems else ''

        cdt_dbt_elems = entry_elem.xpath('./CdtDbtInd')
        cdt_dbt = cdt_dbt_elems[0].text if cdt_dbt_elems else ''

        # Apply debit sign adjustment
        if cdt_dbt == 'DBIT':
            amount = -amount

        # Extract party information
        debtor_elems = entry_elem.xpath('.//Dbtr/Nm')
        debtor = debtor_elems[0].text if debtor_elems else ''

        creditor_elems = entry_elem.xpath('.//Cdtr/Nm')
        creditor = creditor_elems[0].text if creditor_elems else ''

        # Extract references
        ref_elems = entry_elem.xpath('.//Ustrd')
        reference = ''.join([ref.text for ref in ref_elems if ref.text])

        # Extract dates
        val_date_elems = entry_elem.xpath('./ValDt/Dt')
        if not val_date_elems:
            val_date_elems = entry_elem.xpath('./ValDt/DtTm')
        val_date = val_date_elems[0].text if val_date_elems else ''

        booking_date_elems = entry_elem.xpath('./BookgDt/Dt')
        if not booking_date_elems:
            booking_date_elems = entry_elem.xpath('./BookgDt/DtTm')
        booking_date = booking_date_elems[0].text if booking_date_elems else ''

        # Extract address information
        debtor_addr_elems = entry_elem.xpath('.//Dbtr/PstlAdr/AdrLine')
        if not debtor_addr_elems:
            debtor_addr_elems = entry_elem.xpath('.//Dbtr/PstlAdr/StrtNm')
        debtor_addr = debtor_addr_elems[0].text if debtor_addr_elems else ''

        creditor_addr_elems = entry_elem.xpath('.//Cdtr/PstlAdr/AdrLine')
        if not creditor_addr_elems:
            creditor_addr_elems = entry_elem.xpath('.//Cdtr/PstlAdr/StrtNm')
        creditor_addr = creditor_addr_elems[0].text if creditor_addr_elems else ''

        # Apply PII redaction if requested
        if redact_pii:
            if debtor_addr:
                debtor_addr = '***REDACTED***'
            if creditor_addr:
                creditor_addr = '***REDACTED***'

        # Build transaction dictionary
        result = {
            'Amount': amount,
            'Currency': currency,
            'DrCr': cdt_dbt,
            'Debtor': debtor,
            'Creditor': creditor,
            'Reference': reference,
            'ValDt': val_date,
            'BookgDt': booking_date,
            'AccountId': account_id
        }

        # Only add address fields if they exist
        if debtor_addr:
            result['DebtorAddress'] = debtor_addr
        if creditor_addr:
            result['CreditorAddress'] = creditor_addr

        return result

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the parsed CAMT statement data.

        Returns:
            Dict[str, Any]: Summary information including account details,
            transaction counts, and balance information.
        """
        stats_df = self.get_statement_stats()
        balances_df = self.get_account_balances()

        # Get the first statement's summary (most files have one statement)
        summary = {}
        if not stats_df.empty:
            first_stat = stats_df.iloc[0]
            summary = {
                'account_id': first_stat.get('AccountId', 'Unknown'),
                'statement_date': first_stat.get('StatementCreated', 'Unknown'),
                'transaction_count': first_stat.get('NumTransactions', 0),
                'total_amount': first_stat.get('NetAmount', 0.0),
                'currency': 'Unknown'  # Will be extracted from first transaction if available
            }

            # Extract currency from first transaction
            transactions = self.get_transactions()
            if not transactions.empty:
                summary['currency'] = transactions.iloc[0].get('Currency', 'Unknown')

        # Add balance information if available
        if not balances_df.empty:
            # Find opening and closing balances
            opening_balance = balances_df[balances_df['Code'] == 'OPBD']
            closing_balance = balances_df[balances_df['Code'] == 'CLBD']

            if not opening_balance.empty:
                summary['opening_balance'] = opening_balance.iloc[0]['Amount']
            if not closing_balance.empty:
                summary['closing_balance'] = closing_balance.iloc[0]['Amount']

        return summary

    def camt_to_excel(self, filename: str) -> None:
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
