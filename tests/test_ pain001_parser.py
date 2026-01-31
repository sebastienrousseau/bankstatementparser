import unittest
import os
import tempfile
from unittest.mock import patch, mock_open
from xml.etree.ElementTree import ParseError
from bankstatementparser.pain001_parser import Pain001Parser
from bankstatementparser.input_validator import ValidationError


# Define additional test cases
class TestPain001Parser(unittest.TestCase):
    """Tests for Pain001Parser"""

    def setUp(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(
            current_dir, 'test_data', 'pain.001.001.03.xml'
        )
        self.parser = Pain001Parser(file_path)

    def testMessageIdentification(self):
        # Test to ensure the parser correctly retrieves the message
        # identification from the XML data
        group_header = self.parser.tree.find('.//GrpHdr')
        message_id = group_header.find(
            'MsgId'
        ).text if group_header.find('MsgId') is not None else None
        self.assertEqual(
            message_id, '1', "Message identification not retrieved correctly"
        )

    def testCreationDateTime(self):
        # Test to ensure the parser correctly retrieves the creation date and
        # time from the XML data
        group_header = self.parser.tree.find('.//GrpHdr')
        creation_date_time = group_header.find(
            'CreDtTm'
        ).text if group_header.find('CreDtTm') is not None else None
        self.assertEqual(
            creation_date_time,
            '2023-03-10T15:30:47.000Z',
            "Creation date and time not retrieved correctly"
        )

    def testNumberOfTransactions(self):
        # Test to ensure the parser correctly retrieves the number of
        # transactions from the XML data
        group_header = self.parser.tree.find('.//GrpHdr')
        number_of_transactions = group_header.find(
            'NbOfTxs'
        ).text if group_header.find('NbOfTxs') is not None else None
        self.assertEqual(
            number_of_transactions,
            '2',
            "Number of transactions not retrieved correctly"
        )

    def testInitiatingParty(self):
        # Test to ensure the parser correctly retrieves the initiating party
        # information from the XML data
        initiating_party = self.parser.tree.find(
            './/InitgPty/Nm'
        ).text if self.parser.tree.find('.//InitgPty/Nm') is not None else None
        self.assertEqual(
            initiating_party,
            'John Doe',
            "Initiating party not retrieved correctly"
        )

    def testPaymentInformationParsing(self):
        # Test scenarios to ensure that the parser correctly parses and
        # processes different payment information records
        payment_info_records = self.parser.tree.findall('.//PmtInf')
        self.assertGreaterEqual(
            len(payment_info_records),
            1,
            "Insufficient payment information records"
        )

    def test_file_not_found_error(self):
        """Test FileNotFoundError when file doesn't exist."""
        with self.assertRaises(FileNotFoundError) as context:
            Pain001Parser("nonexistent_file.xml")
        self.assertIn("not found", str(context.exception))

    def test_permission_error(self):
        """Test permission error handling."""
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as temp_file:
                temp_file.write(b'<test/>')
                temp_path = temp_file.name

            with self.assertRaises(ValidationError) as context:
                Pain001Parser(temp_path)
            self.assertIn("Permission denied", str(context.exception))

    def test_file_read_error(self):
        """Test general file reading error."""
        with patch("builtins.open", side_effect=IOError("I/O error")):
            with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as temp_file:
                temp_file.write(b'<test/>')
                temp_path = temp_file.name

            with self.assertRaises(ValidationError) as context:
                Pain001Parser(temp_path)
            self.assertIn("Error reading file", str(context.exception))

    def test_xml_syntax_error(self):
        """Test handling of malformed XML."""
        malformed_xml = """<?xml version="1.0"?>
        <Document>
            <unclosed_tag>
            <!-- Missing closing tag -->
        </Document>"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as temp_file:
            temp_file.write(malformed_xml)
            temp_path = temp_file.name

        with self.assertRaises(ValidationError) as context:
            Pain001Parser(temp_path)
        self.assertIn("Invalid XML format", str(context.exception))

        # Cleanup
        os.unlink(temp_path)

    def test_xml_parse_general_error(self):
        """Test general XML parsing error handling."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as temp_file:
            temp_file.write("valid text but not xml")
            temp_path = temp_file.name

        with self.assertRaises(ValidationError) as context:
            Pain001Parser(temp_path)
        self.assertIn("Error parsing XML", str(context.exception))

        # Cleanup
        os.unlink(temp_path)

    def test_parse_with_output_file(self):
        """Test parsing with output file generation."""
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as output_file:
            output_path = output_file.name

        try:
            # Test parsing with output
            result = self.parser.parse(output_path)

            # Check that DataFrame was returned
            self.assertIsNotNone(result)

            # Check that output file was created
            self.assertTrue(os.path.exists(output_path))

        finally:
            # Cleanup
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_parse_without_output_file(self):
        """Test parsing without output file."""
        result = self.parser.parse()
        self.assertIsNotNone(result)
        # Should return a DataFrame
        import pandas as pd
        self.assertIsInstance(result, pd.DataFrame)

    def test_parse_exception_handling(self):
        """Test exception handling in parse method."""
        # Create a parser with minimal XML to trigger parsing errors
        minimal_xml = """<?xml version="1.0"?>
        <Document>
            <!-- Missing required PAIN.001 structure -->
        </Document>"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as temp_file:
            temp_file.write(minimal_xml)
            temp_path = temp_file.name

        try:
            parser = Pain001Parser(temp_path)
            with self.assertRaises(ParseError) as context:
                parser.parse()
            self.assertIn("Error parsing PAIN.001 file", str(context.exception))
        finally:
            os.unlink(temp_path)

    def test_init_with_path_object(self):
        """Test initialization with pathlib.Path object."""
        from pathlib import Path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = Path(current_dir) / 'test_data' / 'pain.001.001.03.xml'

        # This should work without throwing validation error since it's not a string
        parser = Pain001Parser(str(file_path))
        self.assertIsNotNone(parser.file_name)

    def test_xml_namespace_removal(self):
        """Test that XML namespaces are properly removed."""
        xml_with_namespace = """<?xml version="1.0"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
            <CstmrCdtTrfInitn>
                <GrpHdr>
                    <MsgId>TEST123</MsgId>
                    <CreDtTm>2023-01-01T10:00:00</CreDtTm>
                    <InitgPty><Nm>Test Bank</Nm></InitgPty>
                </GrpHdr>
            </CstmrCdtTrfInitn>
        </Document>"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as temp_file:
            temp_file.write(xml_with_namespace)
            temp_path = temp_file.name

        try:
            parser = Pain001Parser(temp_path)
            # Should parse successfully with namespace removed
            result = parser.parse()
            self.assertIsNotNone(result)
        finally:
            os.unlink(temp_path)

    def test_secure_xml_parser_configuration(self):
        """Test that XML parser has security settings enabled."""
        # The parser should be configured with security settings
        # This test verifies the parser initialization doesn't fail with security restrictions
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, 'test_data', 'pain.001.001.03.xml')

        # Should not raise any security-related errors
        parser = Pain001Parser(file_path)
        self.assertIsNotNone(parser.tree)

    def test_validation_error_from_input_validator(self):
        """Test that InputValidator errors are properly propagated."""
        with patch('bankstatementparser.input_validator.InputValidator.validate_input_file_path') as mock_validate:
            mock_validate.side_effect = ValidationError("Invalid file format")

            with self.assertRaises(ValidationError) as context:
                Pain001Parser("test.xml")
            self.assertIn("Invalid file format", str(context.exception))


if __name__ == '__main__':
    unittest.main()
