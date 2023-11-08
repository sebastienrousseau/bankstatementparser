import unittest
from bankstatementparser.camt_parser import CamtParser
import os


class TestCamtParser(unittest.TestCase):
    def setUp(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(
            current_dir,
            'test_data',
            'camt.053.001.02.xml'
        )
        self.parser = CamtParser(file_path)

    def test_init(self):
        self.assertIsNotNone(self.parser)
        self.assertIsNotNone(self.parser.tree)
        self.assertIsInstance(self.parser.definitions, dict)


if __name__ == '__main__':
    unittest.main()
