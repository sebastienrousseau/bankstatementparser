
import unittest
from bankstatementparser.cli import BankStatementCLI

class TestBankStatementCLI(unittest.TestCase):
    def setUp(self):
        self.cli = BankStatementCLI()

    def test_init(self):
        self.assertIsNotNone(self.cli)
        self.assertIsNotNone(self.cli.parser)

    # Add more tests for other methods of BankStatementCLI here

if __name__ == '__main__':
    unittest.main()
