"""
Comprehensive tests for input_validator module.

Tests to achieve high coverage of input validation functionality.
"""

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from bankstatementparser.input_validator import (
    InputValidator,
    ValidationError,
)


class TestInputValidator(unittest.TestCase):
    """Test InputValidator class comprehensively."""

    def setUp(self):
        """Set up test environment."""
        self.validator = InputValidator()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_default(self):
        """Test default initialization."""
        validator = InputValidator()
        self.assertEqual(
            validator.max_file_size, InputValidator.MAX_FILE_SIZE_BYTES
        )

    def test_init_custom_size(self):
        """Test initialization with custom max file size."""
        custom_size = 50 * 1024 * 1024  # 50MB
        validator = InputValidator(max_file_size=custom_size)
        self.assertEqual(validator.max_file_size, custom_size)

    def test_validate_input_file_path_empty_string(self):
        """Test validation with empty string."""
        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_input_file_path("")
        self.assertIn("File path cannot be empty", str(cm.exception))

    def test_validate_input_file_path_none(self):
        """Test validation with None."""
        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_input_file_path(None)
        self.assertIn("must be a non-empty string", str(cm.exception))

    def test_validate_input_file_path_non_string(self):
        """Test validation with non-string input."""
        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_input_file_path(123)
        self.assertIn("must be a non-empty string", str(cm.exception))

    def test_validate_input_file_path_whitespace_only(self):
        """Test validation with whitespace-only string."""
        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_input_file_path("   \t\n  ")
        self.assertIn(
            "cannot be empty or whitespace only", str(cm.exception)
        )

    def test_validate_input_file_path_dangerous_patterns(self):
        """Test detection of dangerous path patterns."""
        dangerous_patterns = [
            "../test.xml",
            "..\\test.xml",
            "/./test.xml",
            "~/test.xml",
            "${HOME}/test.xml",
            "%HOME%/test.xml",
        ]

        for pattern in dangerous_patterns:
            with self.assertRaises(ValidationError) as cm:
                self.validator.validate_input_file_path(pattern)
            self.assertIn("dangerous path pattern", str(cm.exception))

    def test_validate_input_file_path_blocked_directories(self):
        """Test blocking of system directories."""
        blocked_paths = [
            "/etc/test.xml",
            "/bin/test.xml",
            "/sys/test.xml",
            "/proc/test.xml",
            "C:\\Windows\\test.xml",
            "/System/test.xml",
        ]

        for path in blocked_paths:
            with self.assertRaises(ValidationError) as cm:
                self.validator.validate_input_file_path(path)
            self.assertIn("system directory blocked", str(cm.exception))

    def test_validate_input_file_path_invalid_format(self):
        """Test handling of invalid path formats."""
        # This is tricky to test portably, but we can try some edge cases
        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = ValueError("Invalid path")
            with self.assertRaises(ValidationError) as cm:
                self.validator.validate_input_file_path("test.xml")
            self.assertIn("Invalid file path format", str(cm.exception))

    def test_validate_input_file_path_file_not_found(self):
        """Test handling of non-existent files."""
        with self.assertRaises(FileNotFoundError) as cm:
            self.validator.validate_input_file_path(
                "/nonexistent/file.xml"
            )
        self.assertIn("Input file not found", str(cm.exception))

    def test_validate_input_file_path_not_a_file(self):
        """Test handling when path exists but is not a file."""
        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_input_file_path("/tmp")
        self.assertIn("not a file", str(cm.exception))

    def test_validate_input_file_path_not_readable(self):
        """Test handling of unreadable files."""
        # Create a file and remove read permissions
        test_file = os.path.join(self.temp_dir, "test.xml")
        with open(test_file, "w") as f:
            f.write("<?xml version='1.0'?><Document></Document>")
        os.chmod(test_file, 0o000)

        try:
            with self.assertRaises(ValidationError) as cm:
                self.validator.validate_input_file_path(test_file)
            self.assertIn("not readable", str(cm.exception))
        finally:
            os.chmod(
                test_file, 0o644
            )  # Restore permissions for cleanup

    def test_validate_input_file_path_invalid_extension(self):
        """Test rejection of invalid file extensions."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("content")

        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_input_file_path(test_file)
        self.assertIn("Invalid input file extension", str(cm.exception))

    def test_validate_input_file_path_file_too_small(self):
        """Test rejection of files that are too small."""
        test_file = os.path.join(self.temp_dir, "empty.xml")
        with open(test_file, "w"):
            pass  # Create empty file

        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_input_file_path(test_file)
        self.assertIn("too small", str(cm.exception))

    def test_validate_input_file_path_file_too_large(self):
        """Test rejection of files that are too large."""
        # Create a validator with small max size for testing
        small_validator = InputValidator(max_file_size=100)  # 100 bytes

        test_file = os.path.join(self.temp_dir, "large.xml")
        with open(test_file, "w") as f:
            f.write(
                "<?xml version='1.0'?><Document>"
                + "A" * 200
                + "</Document>"
            )

        with self.assertRaises(ValidationError) as cm:
            small_validator.validate_input_file_path(test_file)
        self.assertIn("too large", str(cm.exception))

    def test_validate_input_file_path_valid_file(self):
        """Test successful validation of a valid file."""
        test_file = os.path.join(self.temp_dir, "valid.xml")
        with open(test_file, "w") as f:
            f.write("<?xml version='1.0'?><Document></Document>")

        result = self.validator.validate_input_file_path(test_file)
        self.assertIsInstance(result, Path)
        self.assertTrue(result.exists())

    def test_validate_output_file_path_empty_string(self):
        """Test output validation with empty string."""
        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_output_file_path("")
        self.assertIn(
            "cannot be empty or whitespace only", str(cm.exception)
        )

    def test_validate_output_file_path_none(self):
        """Test output validation with None."""
        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_output_file_path(None)
        self.assertIn("must be a non-empty string", str(cm.exception))

    def test_validate_output_file_path_dangerous_patterns(self):
        """Test output validation blocks dangerous patterns."""
        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_output_file_path("../output.csv")
        self.assertIn("dangerous path pattern", str(cm.exception))

    def test_validate_output_file_path_invalid_format(self):
        """Test handling of invalid output path formats."""
        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = OSError("Invalid path")
            with self.assertRaises(ValidationError) as cm:
                self.validator.validate_output_file_path("output.csv")
            self.assertIn(
                "Invalid output file path format", str(cm.exception)
            )

    def test_validate_output_file_path_create_directory(self):
        """Test creating output directory when it doesn't exist."""
        new_dir = os.path.join(self.temp_dir, "newdir", "subdir")
        output_file = os.path.join(new_dir, "output.csv")

        result = self.validator.validate_output_file_path(output_file)
        self.assertIsInstance(result, Path)
        self.assertTrue(os.path.exists(new_dir))

    def test_validate_xml_content_string(self):
        """Test validation of XML content provided as a string."""
        xml_bytes, source_name = self.validator.validate_xml_content(
            "<?xml version='1.0'?><Document></Document>",
            source_name="statement.xml",
        )

        self.assertEqual(source_name, "statement.xml")
        self.assertIsInstance(xml_bytes, bytes)
        self.assertIn(b"<Document>", xml_bytes)

    def test_validate_xml_content_bytes(self):
        """Test validation of XML content provided as bytes."""
        xml_bytes, source_name = self.validator.validate_xml_content(
            b"<?xml version='1.0'?><Document></Document>",
            source_name="nested/path/statement.xml",
        )

        self.assertEqual(source_name, "nested/path/statement.xml")
        self.assertIsInstance(xml_bytes, bytes)

    def test_validate_xml_content_rejects_zip_payload(self):
        """Test that ZIP/binary payloads are rejected for in-memory XML parsing."""
        archive_path = os.path.join(self.temp_dir, "statements.zip")
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("statement.xml", "<Document></Document>")

        with open(archive_path, "rb") as f:
            archive_bytes = f.read()

        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_xml_content(
                archive_bytes, source_name="statement.xml"
            )
        self.assertIn("binary data", str(cm.exception))

    def test_validate_xml_content_too_large(self):
        """Test rejection of oversized in-memory XML payloads."""
        small_validator = InputValidator(max_file_size=100)
        xml_content = (
            "<?xml version='1.0'?><Document>"
            + ("A" * 200)
            + "</Document>"
        )

        with self.assertRaises(ValidationError) as cm:
            small_validator.validate_xml_content(
                xml_content, source_name="large.xml"
            )
        self.assertIn("too large", str(cm.exception))

    def test_sanitize_source_name_replaces_control_characters(self):
        """Test source name sanitization for log-safe diagnostics."""
        sanitized = self.validator.sanitize_source_name(
            "unsafe\x00name\u202etest.xml"
        )

        self.assertEqual(sanitized, "unsafe?name?test.xml")

    def test_validate_output_file_path_cannot_create_directory(self):
        """Test handling when output directory cannot be created."""
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            mock_mkdir.side_effect = OSError("Permission denied")

            output_file = os.path.join(
                self.temp_dir, "newdir", "output.csv"
            )
            with self.assertRaises(ValidationError) as cm:
                self.validator.validate_output_file_path(output_file)
            self.assertIn(
                "Cannot create output directory", str(cm.exception)
            )

    def test_validate_output_file_path_directory_not_writable(self):
        """Test handling when output directory is not writable."""
        readonly_dir = os.path.join(self.temp_dir, "readonly")
        os.makedirs(readonly_dir)
        os.chmod(readonly_dir, 0o444)  # Read-only

        try:
            output_file = os.path.join(readonly_dir, "output.csv")
            with self.assertRaises(ValidationError) as cm:
                self.validator.validate_output_file_path(output_file)
            self.assertIn("not writable", str(cm.exception))
        finally:
            os.chmod(readonly_dir, 0o755)  # Restore permissions

    def test_validate_output_file_path_invalid_extension(self):
        """Test rejection of invalid output file extensions."""
        output_file = os.path.join(self.temp_dir, "output.txt")
        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_output_file_path(output_file)
        self.assertIn(
            "Invalid output file extension", str(cm.exception)
        )

    def test_validate_output_file_path_file_exists_warning(self):
        """Test warning when output file already exists."""
        output_file = os.path.join(self.temp_dir, "existing.csv")
        with open(output_file, "w") as f:
            f.write("existing content")

        with patch(
            "bankstatementparser.input_validator.logger"
        ) as mock_logger:
            result = self.validator.validate_output_file_path(
                output_file
            )
            mock_logger.warning.assert_called_once()
            self.assertIsInstance(result, Path)

    def test_validate_output_file_path_valid(self):
        """Test successful validation of output file path."""
        output_file = os.path.join(self.temp_dir, "output.csv")
        result = self.validator.validate_output_file_path(output_file)
        self.assertIsInstance(result, Path)

    def test_validate_file_size_cannot_stat(self):
        """Test file size validation when stat fails."""
        test_file = os.path.join(self.temp_dir, "test.xml")
        with open(test_file, "w") as f:
            f.write("<?xml version='1.0'?><Document></Document>")

        with patch.object(
            InputValidator,
            "_validate_file_size",
            side_effect=ValidationError(
                "Cannot determine file size: Cannot stat"
            ),
        ):
            with self.assertRaises(ValidationError) as cm:
                self.validator.validate_input_file_path(test_file)
            self.assertIn(
                "Cannot determine file size", str(cm.exception)
            )

    def test_validate_input_format_mime_type_warning(self):
        """Test warning for unexpected MIME types."""
        test_file = os.path.join(self.temp_dir, "test.xml")
        with open(test_file, "w") as f:
            f.write("<?xml version='1.0'?><Document></Document>")

        with patch(
            "mimetypes.guess_type",
            return_value=("application/octet-stream", None),
        ):
            with patch(
                "bankstatementparser.input_validator.logger"
            ) as mock_logger:
                # This should still pass but log a warning
                self.validator.validate_input_file_path(test_file)
                mock_logger.warning.assert_called()

    def test_validate_input_format_no_xml_indicators(self):
        """Test validation when file has no XML indicators."""
        test_file = os.path.join(self.temp_dir, "notxml.xml")
        with open(test_file, "w") as f:
            f.write("This is plain text without XML indicators")

        with patch(
            "bankstatementparser.input_validator.logger"
        ) as mock_logger:
            # Should pass with a warning
            self.validator.validate_input_file_path(test_file)
            mock_logger.warning.assert_called()

    def test_validate_input_format_binary_data(self):
        """Test rejection of binary data."""
        test_file = os.path.join(self.temp_dir, "binary.xml")
        with open(test_file, "wb") as f:
            f.write(b"\x00\x01\x02\x03\x04\x05" * 20)  # Binary data

        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_input_file_path(test_file)
        self.assertIn("binary data", str(cm.exception))

    def test_validate_input_format_unicode_decode_error(self):
        """Test handling of Unicode decode errors."""
        test_file = os.path.join(self.temp_dir, "bad_encoding.xml")
        with open(test_file, "wb") as f:
            f.write(b"\xff\xfe\x00\x00")  # Invalid UTF-8

        with self.assertRaises(ValidationError) as cm:
            self.validator.validate_input_file_path(test_file)
        self.assertIn("not valid UTF-8", str(cm.exception))

    def test_validate_input_format_read_error(self):
        """Test handling of file read errors during format validation."""
        test_file = os.path.join(self.temp_dir, "test.xml")
        with open(test_file, "w") as f:
            f.write("<?xml version='1.0'?><Document></Document>")

        with patch("builtins.open", side_effect=OSError("Read error")):
            with self.assertRaises(ValidationError) as cm:
                self.validator.validate_input_file_path(test_file)
            self.assertIn(
                "Cannot read file for format validation",
                str(cm.exception),
            )

    def test_get_safe_filename_dangerous_chars(self):
        """Test safe filename generation with dangerous characters."""
        dangerous_filename = 'file<>:"/\\|?*.xml'
        safe_filename = self.validator.get_safe_filename(
            dangerous_filename
        )
        self.assertEqual(safe_filename, "file_________.xml")

    def test_get_safe_filename_leading_trailing_dots(self):
        """Test safe filename generation removes leading/trailing dots and spaces."""
        filename = "...  file.xml  ..."
        safe_filename = self.validator.get_safe_filename(filename)
        self.assertEqual(safe_filename, "file.xml")

    def test_get_safe_filename_empty_result(self):
        """Test safe filename generation with empty result."""
        filename = "   ...   "  # This will become empty after stripping
        safe_filename = self.validator.get_safe_filename(filename)
        self.assertEqual(safe_filename, "unnamed_file")

    def test_get_safe_filename_too_long(self):
        """Test safe filename generation with very long names."""
        long_name = "a" * 300 + ".xml"
        safe_filename = self.validator.get_safe_filename(long_name)
        self.assertTrue(len(safe_filename) <= 255)
        self.assertTrue(safe_filename.endswith(".xml"))

    def test_class_constants(self):
        """Test class constants are defined correctly."""
        self.assertIsInstance(InputValidator.MAX_FILE_SIZE_BYTES, int)
        self.assertIsInstance(InputValidator.MIN_FILE_SIZE_BYTES, int)
        self.assertIsInstance(
            InputValidator.ALLOWED_INPUT_EXTENSIONS, set
        )
        self.assertIsInstance(
            InputValidator.ALLOWED_OUTPUT_EXTENSIONS, set
        )
        self.assertIsInstance(InputValidator.DANGEROUS_PATTERNS, list)
        self.assertIsInstance(InputValidator.BLOCKED_DIRECTORIES, set)

        # Verify some expected values
        self.assertIn(".xml", InputValidator.ALLOWED_INPUT_EXTENSIONS)
        self.assertIn(".csv", InputValidator.ALLOWED_OUTPUT_EXTENSIONS)
        self.assertIn("/etc", InputValidator.BLOCKED_DIRECTORIES)

    def test_case_insensitive_extensions(self):
        """Test that file extensions are handled case-insensitively."""
        test_file = os.path.join(self.temp_dir, "test.XML")  # Uppercase
        with open(test_file, "w") as f:
            f.write("<?xml version='1.0'?><Document></Document>")

        # Should work with uppercase extension
        result = self.validator.validate_input_file_path(test_file)
        self.assertIsInstance(result, Path)

    def test_whitespace_stripping(self):
        """Test that whitespace is properly stripped from paths."""
        test_file = os.path.join(self.temp_dir, "test.xml")
        with open(test_file, "w") as f:
            f.write("<?xml version='1.0'?><Document></Document>")

        # Test with leading/trailing whitespace
        result = self.validator.validate_input_file_path(
            f"  {test_file}  \t\n"
        )
        self.assertIsInstance(result, Path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
