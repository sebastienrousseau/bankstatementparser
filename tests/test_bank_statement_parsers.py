import unittest
from bankstatementparser.bank_statement_parsers import FileParserError
from bankstatementparser.bank_statement_parsers import Pain001Parser
import os


class TestFileParserError(unittest.TestCase):
    def test_file_parser_error(self):
        with self.assertRaises(FileParserError):
            raise FileParserError("This is a file parser error")


class TestPain001Parser(unittest.TestCase):
    def setUp(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(
            current_dir,
            'test_data',
            'pain.001.001.03.xml'
        )
        self.parser = Pain001Parser(file_path)

    def test_init(self):
        self.assertIsNotNone(self.parser)
        self.assertEqual(len(self.parser.batches), 6)

        # Check attributes of the first batch
        first_batch = self.parser.batches[0]
        pmt_inf_id = first_batch.find('.//PmtInfId')
        self.assertIsNotNone(pmt_inf_id)
        self.assertEqual(pmt_inf_id.text, 'Payment-Info-12345')

        # Check the number of payments
        self.assertEqual(len(self.parser.payments), 6)

        # Check attributes of the first payment
        first_payment = self.parser.payments[0]
        self.assertEqual(first_payment['Name'], 'Global Tech')
        self.assertEqual(first_payment['Amount'], 150.0)
        self.assertEqual(first_payment['Currency'], 'EUR')


if __name__ == '__main__':
    unittest.main()
