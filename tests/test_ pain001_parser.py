import unittest
import os
from bankstatementparser.pain001_parser import Pain001Parser

# Define additional test cases
class TestPain001Parser(unittest.TestCase):
    """Tests for Pain001Parser"""

    def setUp(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, 'test_data', 'pain.001.001.03.xml')
        self.parser = Pain001Parser(file_path)

    def testMessageIdentification(self):
        # Test to ensure the parser correctly retrieves the message identification from the XML data
        group_header = self.parser.tree.find('.//GrpHdr')
        message_id = group_header.find('MsgId').text if group_header.find('MsgId') is not None else None
        self.assertEqual(message_id, '1', "Message identification not retrieved correctly")

    def testCreationDateTime(self):
        # Test to ensure the parser correctly retrieves the creation date and time from the XML data
        group_header = self.parser.tree.find('.//GrpHdr')
        creation_date_time = group_header.find('CreDtTm').text if group_header.find('CreDtTm') is not None else None
        self.assertEqual(creation_date_time, '2023-03-10T15:30:47.000Z', "Creation date and time not retrieved correctly")

    def testNumberOfTransactions(self):
        # Test to ensure the parser correctly retrieves the number of transactions from the XML data
        group_header = self.parser.tree.find('.//GrpHdr')
        number_of_transactions = group_header.find('NbOfTxs').text if group_header.find('NbOfTxs') is not None else None
        self.assertEqual(number_of_transactions, '2', "Number of transactions not retrieved correctly")

    def testInitiatingParty(self):
        # Test to ensure the parser correctly retrieves the initiating party information from the XML data
        initiating_party = self.parser.tree.find('.//InitgPty/Nm').text if self.parser.tree.find('.//InitgPty/Nm') is not None else None
        self.assertEqual(initiating_party, 'John Doe', "Initiating party not retrieved correctly")

    def testPaymentInformationParsing(self):
        # Test scenarios to ensure that the parser correctly parses and processes different payment information records
        payment_info_records = self.parser.tree.findall('.//PmtInf')
        self.assertGreaterEqual(len(payment_info_records), 1, "Insufficient payment information records")

if __name__ == '__main__':
    unittest.main()