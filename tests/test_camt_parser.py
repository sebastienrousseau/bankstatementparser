import os
import unittest
import zipfile

from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.input_validator import ValidationError


class TestCamtParser(unittest.TestCase):
    def setUp(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(
            current_dir, "test_data", "camt.053.001.02.xml"
        )
        self.parser = CamtParser(file_path)

    def test_init(self):
        self.assertIsNotNone(self.parser)
        self.assertIsNotNone(self.parser.tree)
        self.assertIsInstance(self.parser.definitions, dict)

    def test_from_string_matches_file_backed_parser(self):
        with open(self.parser.file_name, encoding="utf-8") as f:
            xml_text = f.read()

        memory_parser = CamtParser.from_string(
            xml_text, source_name="statement.xml"
        )

        self.assertEqual(
            self.parser.parse().to_dict("records"),
            memory_parser.parse().to_dict("records"),
        )

    def test_from_bytes_supports_zip_loaded_xml(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        zip_path = os.path.join(
            current_dir, "test_data", "camt_bundle.zip"
        )

        with zipfile.ZipFile(zip_path, "w") as zf:
            with open(self.parser.file_name, "rb") as xml_file:
                zf.writestr(
                    "nested/camt.053.001.02.xml", xml_file.read()
                )

        try:
            with zipfile.ZipFile(zip_path) as zf:
                xml_bytes = zf.read("nested/camt.053.001.02.xml")

            memory_parser = CamtParser.from_bytes(
                xml_bytes,
                source_name="nested/camt.053.001.02.xml",
            )

            self.assertEqual(
                self.parser.get_statement_stats().to_dict("records"),
                memory_parser.get_statement_stats().to_dict("records"),
            )
        finally:
            if os.path.exists(zip_path):
                os.unlink(zip_path)

    def test_from_bytes_rejects_zip_archive_bytes(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        zip_path = os.path.join(current_dir, "test_data", "not_xml.zip")

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("statement.xml", "<Document></Document>")

        try:
            with open(zip_path, "rb") as f:
                archive_bytes = f.read()

            with self.assertRaises(ValidationError):
                CamtParser.from_bytes(
                    archive_bytes, source_name="statement.xml"
                )
        finally:
            if os.path.exists(zip_path):
                os.unlink(zip_path)


if __name__ == "__main__":
    unittest.main()
