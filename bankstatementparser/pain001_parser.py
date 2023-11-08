"""
    pain001_parser.py

    Provides a class for parsing PAIN.001 format bank statement files.
"""

import logging
from xml.etree.ElementTree import ParseError
import pandas as pd
from lxml import etree

# Configuring the logging
logger = logging.getLogger(__name__)


class Pain001Parser:
    """
    Class to parse PAIN.001 format bank statement files.
    """

    def __init__(self, file_name):
        """Initialize the parser with the file name.

        Args:
            file_name (str): Path to the PAIN.001 file.
        """
        self.file_name = file_name

        try:
            # Attempt to open and read the file content
            with open(file_name, 'r', encoding='utf-8') as f:
                data = f.read()
        except FileNotFoundError:
            logger.error("File %s not found!", file_name)
            raise
        except Exception as e:
            logger.error(
                "An error occurred while reading the file: %s", str(e)
            )
            raise

        try:
            # Remove the namespace from the XML data for easier parsing
            data = data.replace(
                'xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"', '')
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

    def parse(self, output_file=None):
        try:
            # Get the root element
            root = self.tree.getroottree().getroot()

            # Get the group header
            group_header = root.find('.//CstmrCdtTrfInitn/GrpHdr')

            # Get the message identification
            message_id = group_header.find(
                'MsgId'
            ).text if group_header.find('MsgId') is not None else None
            print("Message Identification:", message_id)

            # Get the creation date and time
            creation_date_time = group_header.find(
                'CreDtTm'
            ).text if group_header.find('CreDtTm') is not None else None
            print("Creation Date and Time:", creation_date_time)

            # Get the number of transactions
            number_of_transactions = group_header.find(
                'NbOfTxs'
            ).text if group_header.find('NbOfTxs') is not None else None
            print("Number of Transactions:", number_of_transactions)

            # Get the initiating party
            initiating_party = group_header.find(
                './/InitgPty/Nm'
            ).text if group_header.find('.//InitgPty/Nm') is not None else None
            print("Initiating Party:", initiating_party)

            # Parse the payment information records
            payment_info_records = root.findall(
                './/CstmrCdtTrfInitn/PmtInf'
            )
            payments = []
            for pmt in payment_info_records:
                payment = {}
                payment['PmtInfId'] = pmt.find(
                    'PmtInfId'
                ).text if pmt.find('PmtInfId') is not None else None
                # Additional payment information parsing omitted for brevity
                payments.append(payment)

            # Create DataFrame from parsed data
            df = pd.DataFrame(payments)

            if output_file:
                # Save the parsed DataFrame to a CSV file
                df.to_csv(output_file, index=False)
                logger.info("Parsed data saved to %s", output_file)

            return df
        except Exception as e:
            raise ParseError(f"Error parsing PAIN.001 file: {e}")
