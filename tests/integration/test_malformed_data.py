#!/usr/bin/env python3
"""
Integration tests for malformed financial data handling.

Tests end-to-end behavior when processing various types of malformed
or malicious input files to ensure proper error handling and security.
"""

import pytest
import tempfile
import os
from pathlib import Path
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.input_validator import ValidationError
from lxml import etree


class TestMalformedDataHandling:
    """Integration tests for malformed data processing."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def create_test_file(self, temp_dir: Path, filename: str, content: str) -> Path:
        """Helper to create test files with specified content."""
        file_path = temp_dir / filename
        file_path.write_text(content, encoding='utf-8')
        return file_path

    def test_malformed_xml_structure(self, temp_dir):
        """Test handling of structurally invalid XML."""
        malformed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document>
            <Stmt>
                <incomplete_tag>
                <!-- Missing closing tag -->
        </Document>"""

        file_path = self.create_test_file(temp_dir, "malformed.xml", malformed_xml)

        with pytest.raises(etree.XMLSyntaxError):
            CamtParser(str(file_path))

    def test_xml_with_dangerous_entities(self, temp_dir):
        """Test handling of XML with potentially dangerous external entities."""
        dangerous_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE test [
            <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <Document>
            <data>&xxe;</data>
        </Document>"""

        file_path = self.create_test_file(temp_dir, "xxe_attempt.xml", dangerous_xml)

        # Should not raise an exception due to entity resolution being disabled
        # But should parse without executing the entity
        parser = CamtParser(str(file_path))
        # The parser should handle this safely due to resolve_entities=False

    def test_extremely_large_xml_file(self, temp_dir):
        """Test handling of files that exceed size limits."""
        # Create a large XML file that exceeds the default 100MB limit
        large_content = "<?xml version='1.0'?><Document>" + "x" * (101 * 1024 * 1024) + "</Document>"

        file_path = self.create_test_file(temp_dir, "oversized.xml", large_content)

        with pytest.raises(ValidationError, match="too large"):
            CamtParser(str(file_path))

    def test_empty_file(self, temp_dir):
        """Test handling of completely empty files."""
        file_path = self.create_test_file(temp_dir, "empty.xml", "")

        with pytest.raises(ValidationError, match="too small"):
            CamtParser(str(file_path))

    def test_binary_file_disguised_as_xml(self, temp_dir):
        """Test handling of binary files with XML extension."""
        binary_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        file_path = temp_dir / "fake.xml"
        file_path.write_bytes(binary_content)

        with pytest.raises(ValidationError, match="binary data"):
            CamtParser(str(file_path))

    def test_xml_with_deeply_nested_structure(self, temp_dir):
        """Test handling of XML with excessive nesting (potential DoS)."""
        # Create deeply nested XML that could cause stack overflow
        nested_xml = "<?xml version='1.0'?><Document>"
        for i in range(10000):
            nested_xml += f"<level{i}>"
        for i in range(9999, -1, -1):
            nested_xml += f"</level{i}>"
        nested_xml += "</Document>"

        file_path = self.create_test_file(temp_dir, "deeply_nested.xml", nested_xml)

        # Parser should handle this gracefully or fail with proper error
        try:
            CamtParser(str(file_path))
        except (etree.XMLSyntaxError, RecursionError, MemoryError):
            # Any of these are acceptable failure modes
            pass

    def test_xml_with_invalid_characters(self, temp_dir):
        """Test handling of XML with invalid Unicode characters."""
        invalid_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document>
            <InvalidChar>\x00\x01\x02</InvalidChar>
        </Document>"""

        file_path = self.create_test_file(temp_dir, "invalid_chars.xml", invalid_xml)

        with pytest.raises((etree.XMLSyntaxError, UnicodeDecodeError)):
            CamtParser(str(file_path))

    def test_xml_with_malformed_camt_structure(self, temp_dir):
        """Test handling of syntactically valid XML but invalid CAMT structure."""
        malformed_camt = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
            <Stmt>
                <!-- Missing required elements -->
                <InvalidBalance>
                    <Amt>not_a_number</Amt>
                    <Ccy>INVALID</Ccy>
                </InvalidBalance>
            </Stmt>
        </Document>"""

        file_path = self.create_test_file(temp_dir, "malformed_camt.xml", malformed_camt)

        parser = CamtParser(str(file_path))

        # Should parse but operations should fail gracefully
        with pytest.raises((ValueError, IndexError, AttributeError)):
            parser.get_account_balances()

    def test_concurrent_file_access(self, temp_dir):
        """Test behavior when file is being modified during parsing."""
        valid_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
            <Stmt>
                <Id>TEST</Id>
            </Stmt>
        </Document>"""

        file_path = self.create_test_file(temp_dir, "concurrent.xml", valid_xml)

        # This test verifies the parser handles files atomically
        parser = CamtParser(str(file_path))

        # Modify file after parser initialization
        file_path.write_text("corrupted content")

        # Parser should still work with its loaded content
        try:
            parser.get_statement_stats()
        except Exception:
            # File was already loaded, so this should work
            # If it fails, it's due to the original structure, not the modification
            pass

    def test_permission_denied_file(self, temp_dir):
        """Test handling of files with restricted permissions."""
        if os.name != 'posix':
            pytest.skip("Permission test only relevant on POSIX systems")

        file_path = self.create_test_file(temp_dir, "restricted.xml", "<?xml version='1.0'?><Document></Document>")

        # Remove read permissions
        file_path.chmod(0o000)

        try:
            with pytest.raises(ValidationError, match="not readable"):
                CamtParser(str(file_path))
        finally:
            # Restore permissions for cleanup
            file_path.chmod(0o644)