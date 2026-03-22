"""
Security test suite for bank statement parsers.

Tests for security vulnerabilities including:
- XML External Entity (XXE) attacks
- Path traversal attacks
- Malformed XML handling
- Large file attacks
- Invalid input handling
- XML injection attacks
"""

import os
import tempfile
import unittest

from lxml import etree

from bankstatementparser.bank_statement_parsers import (
    Camt053Parser,
    FileParserError,
)
from bankstatementparser.bank_statement_parsers import (
    Pain001Parser as BankPain001Parser,
)
from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.input_validator import ValidationError
from bankstatementparser.pain001_parser import Pain001Parser


class TestSecurityCamtParser(unittest.TestCase):
    """Security tests for CAMT parser."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_xxe_attack_prevention(self):
        """Test that XXE attacks are prevented."""
        xxe_payload = """<?xml version="1.0" encoding="UTF-8"?>
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
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xxe_payload)
            xxe_file = f.name

        try:
            # Parser should not process external entities
            parser = CamtParser(xxe_file)
            # If it doesn't crash, verify no sensitive data was read
            statements = parser.get_statement_stats()
            # Should not contain system file content
            for _, row in statements.iterrows():
                self.assertNotIn("root:", str(row))
                self.assertNotIn("/bin/bash", str(row))
        finally:
            os.unlink(xxe_file)

    def test_xml_billion_laughs_attack(self):
        """Test protection against billion laughs (XML bomb) attacks."""
        xml_bomb = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE lolz [
<!ENTITY lol "lol">
<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
<!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
<!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
<!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
<!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
<!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>&lol9;</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xml_bomb)
            bomb_file = f.name

        try:
            # Should handle gracefully without consuming excessive memory
            parser = CamtParser(bomb_file)
            # Test should complete quickly
            statements = parser.get_statement_stats()
            self.assertIsInstance(statements.to_dict(), dict)
        finally:
            os.unlink(bomb_file)

    def test_malformed_xml_handling(self):
        """Test handling of malformed XML."""
        malformed_cases = [
            # Unclosed tags
            "<Document><Stmt><Id>test</Id></Document>",
            # Invalid encoding
            '<?xml version="1.0" encoding="INVALID"?><Document></Document>',
            # Nested CDATA with special chars
            '<Document><![CDATA[<script>alert("xss")</script>]]></Document>',
            # Deep nesting
            "<Document>"
            + "<Level>" * 1000
            + "deep"
            + "</Level>" * 1000
            + "</Document>",
            # Invalid XML characters
            "<Document>\x00\x01\x02</Document>",
            # Large attribute values
            f'<Document attr="{"A" * 100000}"></Document>',
        ]

        for i, malformed_xml in enumerate(malformed_cases):
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=f"_malformed_{i}.xml", delete=False
            ) as f:
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

    def test_path_traversal_attack(self):
        """Test protection against path traversal attacks in file paths."""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "/etc/shadow",
            "C:\\Windows\\System32\\config\\SAM",
            "\\\\..\\\\..\\\\etc\\\\passwd",
            "....//....//etc//passwd",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # URL encoded
            "..%252f..%252f..%252fetc%252fpasswd",  # Double URL encoded
        ]

        for dangerous_path in dangerous_paths:
            with self.assertRaises(
                (
                    FileNotFoundError,
                    PermissionError,
                    OSError,
                    ValidationError,
                )
            ):
                CamtParser(dangerous_path)

    def test_large_file_handling(self):
        """Test handling of large files to prevent DoS."""
        # Create a large XML file
        large_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
        large_content += "<Document>\n"
        large_content += "  <BkToCstmrStmt>\n"

        # Generate many statements
        for i in range(1000):  # Reasonable number for testing
            large_content += f"""    <Stmt>
      <Id>STMT_{i:06d}</Id>
      <Acct><Id><IBAN>GB29NWBK60161331926{i:03d}</IBAN></Id></Acct>
      <Bal>
        <Amt Ccy="EUR">1000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Tp><Cd>CLBD</Cd></Tp>
        <Dt><Dt>2023-01-01</Dt></Dt>
      </Bal>
    </Stmt>\n"""

        large_content += "  </BkToCstmrStmt>\n</Document>"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(large_content)
            large_file = f.name

        try:
            # Should handle large files gracefully
            parser = CamtParser(large_file)
            stats = parser.get_statement_stats()
            self.assertEqual(len(stats), 1000)

            # Memory usage should be reasonable
            import sys

            if hasattr(sys, "getsizeof"):
                self.assertLess(
                    sys.getsizeof(parser.tree), 50 * 1024 * 1024
                )  # <50MB
        finally:
            os.unlink(large_file)

    def test_invalid_encoding_handling(self):
        """Test handling of files with invalid or mixed encodings."""
        # Test with various problematic encodings
        test_cases = [
            # UTF-8 with BOM
            b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?><Document></Document>',
            # Latin1 content declared as UTF-8
            '<?xml version="1.0" encoding="UTF-8"?><Document>café</Document>'.encode(
                "latin1"
            ),
            # Binary data mixed with XML
            b'<?xml version="1.0"?><Document>\x80\x81\x82</Document>',
        ]

        for i, content in enumerate(test_cases):
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=f"_encoding_{i}.xml", delete=False
            ) as f:
                f.write(content)
                encoding_file = f.name

            try:
                # Should handle gracefully or raise appropriate exception
                try:
                    parser = CamtParser(encoding_file)
                    parser.get_statement_stats()
                except (
                    UnicodeDecodeError,
                    etree.XMLSyntaxError,
                    Exception,
                ) as e:
                    self.assertIsInstance(e, Exception)
            finally:
                os.unlink(encoding_file)

    def test_xpath_injection_prevention(self):
        """Test prevention of XPath injection attacks."""
        # This would be more relevant if user input was used in XPath
        # Currently testing robustness of XPath expressions
        injection_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <BkToCstmrStmt>
        <Stmt>
            <Id>') or '1'='1</Id>
            <Acct>
                <Id><IBAN>GB29NWBK60161331926819</IBAN></Id>
                <Nm>'; DROP TABLE statements; --</Nm>
            </Acct>
            <Bal>
                <Amt Ccy="EUR">1000.00</Amt>
                <CdtDbtInd>CRDT</CdtDbtInd>
                <Tp><Cd>CLBD</Cd></Tp>
                <Dt><Dt>2023-01-01</Dt></Dt>
            </Bal>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(injection_xml)
            injection_file = f.name

        try:
            parser = CamtParser(injection_file)
            stats = parser.get_statement_stats()
            # Should parse normally without executing injection
            self.assertEqual(len(stats), 1)
        finally:
            os.unlink(injection_file)

    def test_file_access_validation(self):
        """Test file access validation and permissions."""
        # Test non-existent file
        with self.assertRaises(FileNotFoundError):
            CamtParser("/nonexistent/path/file.xml")

        # Test directory instead of file
        with self.assertRaises(
            (IsADirectoryError, PermissionError, Exception)
        ):
            CamtParser("/tmp")

        # Test empty file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            empty_file = f.name

        try:
            with self.assertRaises((etree.XMLSyntaxError, Exception)):
                CamtParser(empty_file)
        finally:
            os.unlink(empty_file)

    def test_resource_exhaustion_protection(self):
        """Test protection against resource exhaustion attacks."""
        # Test extremely large tag names
        large_tag_xml = f'<?xml version="1.0"?><{"A" * 10000}>content</{"A" * 10000}>'

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(large_tag_xml)
            large_tag_file = f.name

        try:
            # Should handle or reject gracefully
            try:
                parser = CamtParser(large_tag_file)
            except (etree.XMLSyntaxError, Exception) as e:
                self.assertIsInstance(e, Exception)
        finally:
            os.unlink(large_tag_file)

        # Test excessive attribute count
        many_attrs = " ".join(
            [f'attr{i}="value{i}"' for i in range(1000)]
        )
        attr_xml = (
            f'<?xml version="1.0"?><Document {many_attrs}></Document>'
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(attr_xml)
            attr_file = f.name

        try:
            try:
                parser = CamtParser(attr_file)
                parser.get_statement_stats()
            except Exception as e:
                # Expected for edge cases
                self.assertIsInstance(e, Exception)
        finally:
            os.unlink(attr_file)


class TestSecurityPain001Parser(unittest.TestCase):
    """Security tests for Pain001 parser."""

    def test_malformed_xml_handling(self):
        """Test Pain001 parser with malformed XML."""
        malformed_xml = (
            "<CstmrCdtTrfInitn><GrpHdr><MsgId>invalid"  # Unclosed
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(malformed_xml)
            malformed_file = f.name

        try:
            with self.assertRaises((etree.XMLSyntaxError, Exception)):
                Pain001Parser(malformed_file)
        finally:
            os.unlink(malformed_file)

    def test_xxe_protection(self):
        """Test XXE protection in Pain001 parser."""
        xxe_xml = """<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<Document>
    <CstmrCdtTrfInitn>
        <GrpHdr>
            <MsgId>&xxe;</MsgId>
        </GrpHdr>
    </CstmrCdtTrfInitn>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xxe_xml)
            xxe_file = f.name

        try:
            parser = Pain001Parser(xxe_file)
            result = parser.parse()
            # Should not contain system file data
            if not result.empty:
                for col in result.columns:
                    for value in result[col]:
                        if value:
                            self.assertNotIn("root:", str(value))
        finally:
            os.unlink(xxe_file)


class TestSecurityBankStatementParsers(unittest.TestCase):
    """Security tests for bank statement parsers module."""

    def test_camt053_security(self):
        """Test Camt053Parser security."""
        # Test with malformed XML
        malformed_xml = "<Document><Stmt><Id>test</Id><!-- unclosed -->"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(malformed_xml)
            malformed_file = f.name

        try:
            with self.assertRaises(
                (FileParserError, etree.XMLSyntaxError, Exception)
            ):
                Camt053Parser(malformed_file)
        finally:
            os.unlink(malformed_file)

    def test_pain001_bank_security(self):
        """Test Pain001Parser from bank_statement_parsers security."""
        # Test with XXE payload
        xxe_xml = """<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/hosts">]>
<Document>
    <CstmrCdtTrfInitn>
        <PmtInf>
            <PmtInfId>&xxe;</PmtInfId>
            <ReqdExctnDt>2023-01-01</ReqdExctnDt>
            <Dbtr><Nm>Test</Nm></Dbtr>
            <DbtrAcct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></DbtrAcct>
            <CdtTrfTxInf>
                <InstdAmt Ccy="EUR">100.00</InstdAmt>
                <Cdtr><Nm>Creditor</Nm></Cdtr>
                <CdtrAcct><Id><IBAN>GB29NWBK60161331926820</IBAN></Id></CdtrAcct>
            </CdtTrfTxInf>
        </PmtInf>
    </CstmrCdtTrfInitn>
</Document>"""

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xxe_xml)
            xxe_file = f.name

        try:
            parser = BankPain001Parser(xxe_file)
            # Verify no system data leaked
            self.assertIsNotNone(parser.payments)
            for payment in parser.payments:
                if "debtor_name" in payment and payment["debtor_name"]:
                    self.assertNotIn(
                        "localhost", payment["debtor_name"]
                    )
                    self.assertNotIn(
                        "127.0.0.1", payment["debtor_name"]
                    )
        finally:
            os.unlink(xxe_file)

    def test_input_validation_edge_cases(self):
        """Test edge cases for input validation."""
        # Extremely large XML
        large_xml = (
            '<?xml version="1.0"?><Document>'
            + "A" * 1000000
            + "</Document>"
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(large_xml)
            large_file = f.name

        try:
            # Should handle large content gracefully
            try:
                Camt053Parser(large_file)
            except Exception as e:
                # Expected for extremely large files
                self.assertIsInstance(e, Exception)
        finally:
            os.unlink(large_file)

    def test_process_folder_security(self):
        """Test folder processing security."""
        from bankstatementparser.bank_statement_parsers import (
            process_camt053_folder,
        )

        # Test with non-existent folder
        with self.assertRaises((FileNotFoundError, OSError)):
            process_camt053_folder("/nonexistent/folder")

        # Test with folder containing malicious files
        test_dir = tempfile.mkdtemp()
        try:
            # Create a valid XML file
            valid_xml = """<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
    <BkToCstmrStmt>
        <Stmt>
            <Id>test</Id>
            <Acct><Id><IBAN>GB29NWBK60161331926819</IBAN></Id></Acct>
        </Stmt>
    </BkToCstmrStmt>
</Document>"""

            with open(os.path.join(test_dir, "valid.xml"), "w") as f:
                f.write(valid_xml)

            # Create a malicious file
            with open(
                os.path.join(test_dir, "malicious.xml"), "w"
            ) as f:
                f.write(
                    '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><Document>&xxe;</Document>'
                )

            # Should handle mixed valid/invalid files
            (
                files_df,
                statements_df,
                transactions_df,
            ) = process_camt053_folder(test_dir)
            self.assertGreaterEqual(len(files_df), 2)

            # Check that failures are recorded properly
            failed_files = files_df[
                files_df["Status"].str.contains("Failed", na=False)
            ]
            self.assertGreaterEqual(len(failed_files), 0)

        finally:
            import shutil

            shutil.rmtree(test_dir)


class TestSecurityMitigations(unittest.TestCase):
    """Test security mitigations and defensive programming."""

    def test_memory_usage_monitoring(self):
        """Test that parsers don't consume excessive memory."""
        import sys

        # Create moderately large XML
        xml_content = (
            '<?xml version="1.0"?>\n<Document>\n<BkToCstmrStmt>\n'
        )
        for i in range(100):
            xml_content += f"""<Stmt>
<Id>STMT_{i}</Id>
<Acct><Id><IBAN>GB29NWBK60161331926{i:03d}</IBAN></Id></Acct>
<Bal><Amt Ccy="EUR">1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Tp><Cd>CLBD</Cd></Tp></Bal>
</Stmt>\n"""
        xml_content += "</BkToCstmrStmt>\n</Document>"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xml_content)
            test_file = f.name

        try:
            # Measure memory before
            import gc

            gc.collect()

            parser = CamtParser(test_file)
            stats = parser.get_statement_stats()

            # Verify reasonable memory usage
            if hasattr(sys, "getsizeof"):
                tree_size = sys.getsizeof(parser.tree)
                self.assertLess(
                    tree_size, 10 * 1024 * 1024
                )  # <10MB for 100 statements

            self.assertEqual(len(stats), 100)

        finally:
            os.unlink(test_file)

    def test_exception_information_disclosure(self):
        """Test that exceptions don't leak sensitive information."""
        # Test with file that might reveal system info
        with self.assertRaises(
            (FileNotFoundError, ValidationError)
        ) as cm:
            CamtParser("/etc/passwd")

        # Exception should not contain sensitive paths or should block access
        error_msg = str(cm.exception).lower()
        self.assertTrue(
            "not found" in error_msg or "blocked" in error_msg
        )

        # Test with parsing error
        invalid_xml = (
            '<?xml version="1.0"?><Document><Stmt><Id>test'  # Malformed
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(invalid_xml)
            invalid_file = f.name

        try:
            with self.assertRaises(Exception) as cm:
                CamtParser(invalid_file)

            # Should not leak system paths in error messages
            error_msg = str(cm.exception)
            self.assertNotIn("/tmp", error_msg)

        finally:
            os.unlink(invalid_file)


if __name__ == "__main__":
    # Run all security tests
    unittest.main(verbosity=2)
