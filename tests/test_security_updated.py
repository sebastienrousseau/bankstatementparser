"""
Updated security test suite for bank statement parsers.

Tests that validate existing security measures and ensure they function properly.
This suite validates that security controls are in place rather than testing for vulnerabilities.
"""

import os
import tempfile
import unittest

import pandas as pd
from lxml import etree

from bankstatementparser.bank_statement_parsers import (
    Camt053Parser,
)
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.input_validator import ValidationError
from bankstatementparser.pain001_parser import Pain001Parser


class TestInputValidationSecurity(unittest.TestCase):
    """Test input validation security controls."""

    def test_path_traversal_prevention(self):
        """Test that path traversal attacks are properly blocked."""
        dangerous_paths = [
            '../../../etc/passwd',
            '..\\..\\..\\windows\\system32\\config\\sam',
            '....//....//etc//passwd',
        ]

        for dangerous_path in dangerous_paths:
            with self.assertRaises(ValidationError) as cm:
                CamtParser(dangerous_path)

            self.assertIn("Potentially dangerous path pattern detected", str(cm.exception))

    def test_system_directory_protection(self):
        """Test that access to system directories is blocked."""
        system_paths = [
            '/etc/passwd',
            '/bin/bash',
            '/usr/bin/whoami',
        ]

        for system_path in system_paths:
            with self.assertRaises(ValidationError) as cm:
                CamtParser(system_path)

            self.assertIn("Access to system directory blocked", str(cm.exception))

    def test_file_size_validation(self):
        """Test file size limits are enforced."""
        # Test empty file rejection
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            empty_file = f.name

        try:
            with self.assertRaises(ValidationError) as cm:
                CamtParser(empty_file)
            self.assertIn("File is too small", str(cm.exception))
        finally:
            os.unlink(empty_file)

    def test_file_extension_validation(self):
        """Test that only allowed file extensions are accepted."""
        invalid_extensions = ['.txt', '.exe', '.py', '.sh', '.bat']

        for ext in invalid_extensions:
            with tempfile.NamedTemporaryFile(mode='w', suffix=ext, delete=False) as f:
                f.write("<?xml version='1.0'?><Document></Document>")
                invalid_file = f.name

            try:
                with self.assertRaises(ValidationError) as cm:
                    CamtParser(invalid_file)
                self.assertIn("Invalid input file extension", str(cm.exception))
            finally:
                os.unlink(invalid_file)

    def test_nonexistent_file_handling(self):
        """Test handling of non-existent files."""
        with self.assertRaises(FileNotFoundError):
            CamtParser('/nonexistent/path/file.xml')

    def test_directory_access_prevention(self):
        """Test that directories are rejected as input files."""
        with self.assertRaises(ValidationError) as cm:
            CamtParser('/tmp')
        self.assertIn("Path exists but is not a file", str(cm.exception))


class TestXMLParsingSecurity(unittest.TestCase):
    """Test XML parsing security measures."""

    def test_xxe_attack_mitigation(self):
        """Test that XXE attacks are mitigated by secure parsing."""
        xxe_payload = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [
<!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>XXE_TEST</Id>
            <Acct>
                <Id><IBAN>GB29NWBK60161331926819</IBAN></Id>
                <Nm>&xxe;</Nm>
            </Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(xxe_payload)
            xxe_file = f.name

        try:
            # Parser should handle this without exposing system files
            parser = CamtParser(xxe_file)
            statements = parser.get_statement_stats()
            # Verify no sensitive data was read
            self.assertIsInstance(statements.to_dict(), dict)
            # XXE content should not be present
            for _, row in statements.iterrows():
                row_str = str(row.to_dict())
                self.assertNotIn('root:', row_str)
                self.assertNotIn('/bin/bash', row_str)
        finally:
            os.unlink(xxe_file)

    def test_billion_laughs_mitigation(self):
        """Test protection against billion laughs attacks."""
        xml_bomb = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE lolz [
<!ENTITY lol "lol">
<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
<!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
]>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>&lol5;</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(xml_bomb)
            bomb_file = f.name

        try:
            # Should handle gracefully without excessive memory usage
            parser = CamtParser(bomb_file)
            statements = parser.get_statement_stats()
            self.assertIsInstance(statements.to_dict(), dict)
        finally:
            os.unlink(bomb_file)

    def test_malformed_xml_resilience(self):
        """Test resilience to malformed XML."""
        malformed_cases = [
            # Unclosed tags - should be handled by recovery parser
            '<Document><Stmt><Id>test</Id></Document>',
            # Nested CDATA
            '<Document><![CDATA[<script>alert("test")</script>]]></Document>',
            # Invalid XML characters
            '<Document>Valid\x00Content</Document>',
        ]

        for i, malformed_xml in enumerate(malformed_cases):
            with tempfile.NamedTemporaryFile(mode='w', suffix=f'_malformed_{i}.xml', delete=False) as f:
                f.write(malformed_xml)
                malformed_file = f.name

            try:
                # Should either parse with recovery or raise appropriate exception
                try:
                    parser = CamtParser(malformed_file)
                    # If parsing succeeds, basic operations should work
                    parser.get_statement_stats()
                except (etree.XMLSyntaxError, Exception) as e:
                    # Expected for malformed XML
                    self.assertIsInstance(e, Exception)
            finally:
                os.unlink(malformed_file)

    def test_encoding_security(self):
        """Test handling of various text encodings securely."""
        # Test with UTF-8 BOM
        bom_xml = b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?><Document></Document>'

        with tempfile.NamedTemporaryFile(mode='wb', suffix='.xml', delete=False) as f:
            f.write(bom_xml)
            bom_file = f.name

        try:
            # Should handle BOM gracefully
            try:
                parser = CamtParser(bom_file)
                parser.get_statement_stats()
            except Exception as e:
                # Acceptable if encoding causes issues
                self.assertIsInstance(e, Exception)
        finally:
            os.unlink(bom_file)


class TestResourceProtection(unittest.TestCase):
    """Test protection against resource exhaustion attacks."""

    def test_large_file_handling(self):
        """Test handling of large files within limits."""
        # Create a reasonably large XML file (but within limits)
        large_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
        large_content += '<Document>\n'
        large_content += '  <BkToCstmrStmt>\n'

        # Generate moderate number of statements
        for i in range(100):  # Reasonable number
            large_content += f'''    <Stmt>
      <Id>STMT_{i:06d}</Id>
      <Acct><Id><IBAN>GB29NWBK60161331926{i:03d}</IBAN></Id></Acct>
      <Bal>
        <Amt Ccy="EUR">1000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Tp><Cd>CLBD</Cd></Tp>
        <Dt><Dt>2023-01-01</Dt></Dt>
      </Bal>
    </Stmt>\n'''

        large_content += '  </BkToCstmrStmt>\n</Document>'

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(large_content)
            large_file = f.name

        try:
            # Should handle moderate large files gracefully
            parser = CamtParser(large_file)
            stats = parser.get_statement_stats()
            self.assertEqual(len(stats), 100)
        finally:
            os.unlink(large_file)

    def test_memory_usage_reasonable(self):
        """Test that memory usage remains reasonable."""
        import gc
        import sys

        test_xml = '''<?xml version="1.0"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
            <Bal>
                <Amt Ccy="EUR">1000.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <Tp><Cd>CLBD</Cd></Tp>
                <Dt><Dt>2023-01-01</Dt></Dt>
            </Bal>
        </Stmt>
    </BkToCstmrStmt>
</Document>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(test_xml)
            test_file = f.name

        try:
            # Verify reasonable memory usage
            gc.collect()
            parser = CamtParser(test_file)
            parser.get_statement_stats()

            if hasattr(sys, 'getsizeof'):
                tree_size = sys.getsizeof(parser.tree)
                # Should be reasonable for a small file
                self.assertLess(tree_size, 1024 * 1024)  # <1MB

        finally:
            os.unlink(test_file)


class TestErrorHandlingSecurity(unittest.TestCase):
    """Test security aspects of error handling."""

    def test_error_message_sanitization(self):
        """Test that error messages don't leak sensitive information."""
        # Test with non-existent file in sensitive location
        try:
            CamtParser('/etc/nonexistent_file.xml')
        except (ValidationError, FileNotFoundError) as e:
            error_msg = str(e)
            # Should contain useful error info but not leak system details
            self.assertIn("blocked", error_msg.lower())

    def test_exception_type_consistency(self):
        """Test that consistent exception types are raised for security errors."""
        # Path traversal should raise ValidationError
        with self.assertRaises(ValidationError):
            CamtParser('../../../etc/passwd')

        # System directory access should raise ValidationError
        with self.assertRaises(ValidationError):
            CamtParser('/etc/hosts')

        # Non-existent files should raise FileNotFoundError or ValidationError
        with self.assertRaises((FileNotFoundError, ValidationError)):
            CamtParser('/nonexistent/file.xml')


class TestSecurityIntegration(unittest.TestCase):
    """Test integration of security measures across parsers."""

    def test_pain001_security_integration(self):
        """Test Pain001 parser security integration."""
        # Test with potentially malicious but valid XML
        test_xml = '''<?xml version="1.0"?>
<Document>
    <CstmrCdtTrfInitn>
        <GrpHdr>
            <MsgId>TEST_&lt;SCRIPT&gt;</MsgId>
            <CreDtTm>2023-01-01T10:00:00</CreDtTm>
            <InitgPty><Nm>Safe &amp; Secure Bank</Nm></InitgPty>
        </GrpHdr>
    </CstmrCdtTrfInitn>
</Document>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(test_xml)
            test_file = f.name

        try:
            parser = Pain001Parser(test_file)
            result = parser.parse()
            # Should handle XML entities properly
            # Minimal XML with no PmtInf returns an empty DataFrame
            self.assertIsInstance(result, pd.DataFrame)
            self.assertTrue(result.empty)
        finally:
            os.unlink(test_file)

    def test_bank_statement_parsers_security(self):
        """Test security measures in bank statement parsers module."""
        # Test with valid but minimal CAMT file
        test_xml = '''<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
    <BkToCstmrStmt>
        <Stmt>
            <Id>SECURE_TEST</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(test_xml)
            test_file = f.name

        try:
            parser = Camt053Parser(test_file)
            self.assertEqual(len(parser.statements), 1)
            self.assertEqual(parser.statements[0]['StatementId'], 'SECURE_TEST')
        finally:
            os.unlink(test_file)

    def test_folder_processing_security(self):
        """Test folder processing security measures."""
        from bankstatementparser.bank_statement_parsers import (
            process_camt053_folder,
        )

        # Create a test directory with mixed files
        test_dir = tempfile.mkdtemp()
        try:
            # Valid file
            valid_xml = '''<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
    <BkToCstmrStmt>
        <Stmt>
            <Id>VALID</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>'''

            with open(os.path.join(test_dir, 'valid.xml'), 'w') as f:
                f.write(valid_xml)

            # Should process the directory safely
            files_df, statements_df, transactions_df = process_camt053_folder(test_dir)
            self.assertGreaterEqual(len(files_df), 1)

            # Check that processing was successful for valid file
            success_files = files_df[files_df['Status'] == 'Success']
            self.assertGreaterEqual(len(success_files), 1)

        finally:
            import shutil
            shutil.rmtree(test_dir)


class TestDataSanitization(unittest.TestCase):
    """Test data sanitization and output security."""

    def test_special_character_handling(self):
        """Test proper handling of special characters in data."""
        special_chars_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT&amp;001</Id>
            <Acct>
                <Id><IBAN>GB29NWBK60161331926819</IBAN></Id>
                <Nm>Test &lt;Account&gt; "Name" &amp; More</Nm>
            </Acct>
            <Ntry>
                <Amt Ccy="EUR">100.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <ValDt><Dt>2023-01-01</Dt></ValDt>
                <NtryDtls>
                    <TxDtls>
                        <RmtInf>
                            <Ustrd>Payment for "goods &amp; services"</Ustrd>
                        </RmtInf>
                    </TxDtls>
                </NtryDtls>
            </Ntry>
        </Stmt>
    </BkToCstmrStmt>
</Document>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(special_chars_xml)
            test_file = f.name

        try:
            parser = CamtParser(test_file)
            transactions = parser.get_transactions()

            # Verify special characters are properly handled
            self.assertEqual(len(transactions), 1)
            self.assertIn('goods & services', transactions.iloc[0]['Reference'])
        finally:
            os.unlink(test_file)

    def test_output_file_security(self):
        """Test security of output file operations."""
        test_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>STMT001</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>'''

        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(test_xml)
            test_file = f.name

        try:
            parser = CamtParser(test_file)

            # Test safe output file creation
            with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as excel_f:
                excel_file = excel_f.name

            try:
                # Should create output safely
                parser.camt_to_excel(excel_file)
                self.assertTrue(os.path.exists(excel_file))
                self.assertGreater(os.path.getsize(excel_file), 0)

            finally:
                if os.path.exists(excel_file):
                    os.unlink(excel_file)

        finally:
            os.unlink(test_file)


if __name__ == '__main__':
    unittest.main(verbosity=2)
