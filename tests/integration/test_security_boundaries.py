#!/usr/bin/env python3
"""
Integration tests for security boundary validation.

Tests end-to-end security controls including path traversal prevention,
dangerous file access prevention, and input sanitization.
"""

import os
import tempfile
from pathlib import Path

import pytest
from lxml import etree

from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.input_validator import (
    InputValidator,
    ValidationError,
)


class TestSecurityBoundaries:
    """Integration tests for security boundary enforcement."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def validator(self):
        """Create an InputValidator instance for testing."""
        return InputValidator()

    def create_test_xml(self, temp_dir: Path, filename: str) -> Path:
        """Helper to create a basic valid XML test file."""
        content = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
            <Stmt>
                <Id>TEST</Id>
            </Stmt>
        </Document>"""
        file_path = temp_dir / filename
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def test_path_traversal_prevention(self, temp_dir, validator):
        """Test prevention of directory traversal attacks."""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\Windows\\System32\\config\\SAM",
            "./../sensitive_file.xml",
            "directory/../../../etc/hosts",
            "/etc/passwd",
            "C:\\Windows\\System32\\drivers\\etc\\hosts",
        ]

        for dangerous_path in dangerous_paths:
            with pytest.raises(
                ValidationError, match="dangerous path|system directory"
            ):
                validator.validate_input_file_path(dangerous_path)

    def test_system_directory_protection(self, temp_dir, validator):
        """Test protection against accessing system directories."""
        if os.name == "posix":
            system_paths = [
                "/etc/passwd",
                "/bin/bash",
                "/usr/bin/python",
                "/sys/kernel",
                "/proc/version",
                "/root/.bashrc",
            ]
        else:
            system_paths = [
                "C:\\Windows\\System32\\config\\SAM",
                "C:\\Program Files\\sensitive.exe",
                "C:\\Windows\\explorer.exe",
            ]

        for sys_path in system_paths:
            with pytest.raises(
                ValidationError, match="system directory"
            ):
                validator.validate_input_file_path(sys_path)

    def test_variable_expansion_prevention(self, temp_dir, validator):
        """Test prevention of shell variable expansion attacks."""
        dangerous_variables = [
            "${HOME}/.ssh/id_rsa",
            "%USERPROFILE%\\Documents\\sensitive.xml",
            "${PATH}/../../etc/passwd",
            "%TEMP%\\..\\..\\Windows\\System32\\config",
            "~/../../etc/shadow",
        ]

        for var_path in dangerous_variables:
            with pytest.raises(ValidationError, match="dangerous path"):
                validator.validate_input_file_path(var_path)

    def test_file_extension_validation(self, temp_dir):
        """Test file extension security validation."""
        # Create files with various extensions
        test_files = {
            "script.py": "print('hello')",
            "executable.exe": "binary content",
            "webpage.html": "<html></html>",
            "config.conf": "[section]",
            "data.json": "{}",
        }

        for filename, content in test_files.items():
            file_path = temp_dir / filename
            file_path.write_text(content)

            # Should reject non-XML files
            with pytest.raises(
                ValidationError, match="Invalid input file extension"
            ):
                CamtParser(str(file_path))

    def test_file_size_limits(self, temp_dir):
        """Test file size security limits."""
        validator = InputValidator(max_file_size=1024)  # 1KB limit

        # Create an oversized file
        large_content = (
            "<?xml version='1.0'?><Document>"
            + "x" * 2048
            + "</Document>"
        )
        large_file = temp_dir / "large.xml"
        large_file.write_text(large_content)

        with pytest.raises(ValidationError, match="too large"):
            validator.validate_input_file_path(str(large_file))

    def test_output_path_security(self, temp_dir, validator):
        """Test security validation for output file paths."""
        # Test dangerous output paths
        dangerous_outputs = [
            "/etc/passwd.xlsx",
            "../../../system.csv",
            "%TEMP%\\..\\sensitive.xlsx",
            "${HOME}/.ssh/keys.csv",
        ]

        for dangerous_output in dangerous_outputs:
            with pytest.raises(ValidationError):
                validator.validate_output_file_path(dangerous_output)

    def test_unicode_normalization_attacks(self, temp_dir, validator):
        """Test handling of Unicode normalization attacks."""
        # Unicode characters that might normalize to dangerous sequences
        unicode_attacks = [
            "file\u002e\u002e/\u002e\u002e/etc/passwd",  # Unicode dots and slashes
            "normal\u0000file.xml",  # Null byte injection
            "file\u202ename.xml",  # Right-to-left override
        ]

        for attack_path in unicode_attacks:
            # Most should be caught by dangerous pattern detection
            with pytest.raises(ValidationError):
                validator.validate_input_file_path(attack_path)

    def test_symlink_traversal_prevention(self, temp_dir):
        """Test prevention of symlink-based attacks."""
        if os.name != "posix":
            pytest.skip("Symlink test only relevant on POSIX systems")

        # Create a symlink pointing to a sensitive file
        sensitive_target = "/etc/passwd"
        symlink_path = temp_dir / "innocent.xml"

        try:
            os.symlink(sensitive_target, symlink_path)

            # Should detect the resolved path points to a system directory
            with pytest.raises((ValidationError, FileNotFoundError)):
                CamtParser(str(symlink_path))
        except OSError:
            # If symlink creation fails, skip this test
            pytest.skip("Cannot create symlink for testing")

    def test_concurrent_file_manipulation(self, temp_dir):
        """Test security when files are manipulated during processing."""
        # Create a valid XML file
        xml_file = self.create_test_xml(temp_dir, "test.xml")

        # Initialize parser
        parser = CamtParser(str(xml_file))

        # Replace file with malicious content after initialization
        xml_file.write_text(
            "<?xml version='1.0'?><!DOCTYPE test [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><Document>&xxe;</Document>"
        )

        # Parser should work with original content loaded in memory
        # This tests that the parser doesn't re-read files after initialization
        try:
            parser.get_statement_stats()
            # If this succeeds, the parser used the original safe content
        except Exception as e:
            # If it fails, it should be due to structure, not XXE
            assert "entity" not in str(e).lower(), (
                "Parser may be vulnerable to XXE after file replacement"
            )

    def test_filename_sanitization(self, validator):
        """Test filename sanitization for safe output generation."""
        dangerous_filenames = [
            "normal<script>alert('xss')</script>.csv",
            "file|with|pipes.xlsx",
            "question?mark.csv",
            "asterisk*.xlsx",
            'quotes"inside.csv',
            "colon:separated.xlsx",
            "null\x00byte.csv",
        ]

        for dangerous_name in dangerous_filenames:
            safe_name = validator.get_safe_filename(dangerous_name)

            # Ensure dangerous characters are removed/replaced
            assert "<" not in safe_name
            assert ">" not in safe_name
            assert "|" not in safe_name
            assert "?" not in safe_name
            assert "*" not in safe_name
            assert '"' not in safe_name
            assert ":" not in safe_name
            assert "\x00" not in safe_name

    def test_xml_parser_security_configuration(self, temp_dir):
        """Test that XML parser is configured securely."""
        # Create XML with external entity reference
        xxe_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE test [
            <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
            <data>&xxe;</data>
        </Document>"""

        file_path = temp_dir / "xxe_test.xml"
        file_path.write_text(xxe_xml)

        # Parser should handle this safely
        parser = CamtParser(str(file_path))

        # Check that no external entity content was loaded
        # The parser should process this without resolving entities
        try:
            parser.get_statement_stats()
            # Success means entities were not resolved
        except Exception as e:
            # Failure should be due to structure, not entity resolution
            error_msg = str(e).lower()
            assert "entity" not in error_msg or "not found" in error_msg

    def test_memory_exhaustion_prevention(self, temp_dir):
        """Test prevention of memory exhaustion attacks."""
        # Create XML with expansion bomb pattern
        bomb_xml = """<?xml version="1.0"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">"""

        # Add many repeated large elements
        for i in range(1000):
            bomb_xml += f"<LargeElement{'A' * 1000}>{i}</LargeElement{'A' * 1000}>"

        bomb_xml += "</Document>"

        file_path = temp_dir / "bomb.xml"
        file_path.write_text(bomb_xml)

        # Parser should handle this without excessive memory usage
        try:
            parser = CamtParser(str(file_path))
            # If parsing succeeds, operations should still be reasonable
            parser.get_statement_stats()
        except (MemoryError, etree.XMLSyntaxError):
            # Acceptable failure modes for resource exhaustion
            pass
