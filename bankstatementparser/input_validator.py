# Copyright (C) 2023 Sebastien Rousseau.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
input_validator.py

Provides comprehensive input validation for file paths, sizes, and formats
used throughout the bank statement parser.
"""

import os
import re
import mimetypes
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class ValidationError(FileNotFoundError):
    """Custom exception for validation errors.

    Inherits from FileNotFoundError (which inherits from OSError)
    for backward compatibility with code that catches file-related
    OS errors such as FileNotFoundError, PermissionError, or OSError.
    """
    pass

class InputValidator:
    """Comprehensive input validator for file operations."""

    # Default configuration
    MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100MB default
    MIN_FILE_SIZE_BYTES = 1  # 1 byte minimum

    # Allowed file extensions for input files
    ALLOWED_INPUT_EXTENSIONS = {'.xml', '.XML'}

    # Allowed file extensions for output files
    ALLOWED_OUTPUT_EXTENSIONS = {'.csv', '.CSV', '.xlsx', '.XLSX', '.xls', '.XLS'}

    # Dangerous path patterns to block
    DANGEROUS_PATTERNS = [
        r'\.\.',   # Directory traversal (catches ../.. and ..\.. patterns)
        r'/\./',   # Hidden directory traversal
        r'~/',     # Home directory shortcuts (can be allowed if needed)
        r'\$\{',   # Variable expansion
        r'%[A-Z_]+%',  # Windows environment variables
    ]

    # System directories to block (platform-specific)
    BLOCKED_DIRECTORIES = {
        # Unix/Linux/macOS
        '/etc', '/bin', '/sbin', '/usr/bin', '/usr/sbin', '/sys', '/proc',
        '/dev', '/boot', '/root',
        # Windows
        'C:\\Windows', 'C:\\Program Files', 'C:\\Program Files (x86)',
        'C:\\System32', 'C:\\Windows\\System32',
        # macOS specific
        '/System', '/Library/System', '/private/var/db',
    }

    def __init__(self, max_file_size: Optional[int] = None):
        """
        Initialize the validator with optional custom configuration.

        Args:
            max_file_size: Maximum allowed file size in bytes.
        """
        self.max_file_size = max_file_size or self.MAX_FILE_SIZE_BYTES

    def validate_input_file_path(self, file_path: str) -> Path:
        """
        Validate and sanitize an input file path.

        Args:
            file_path: Raw file path string to validate.

        Returns:
            Path: Validated and resolved path object.

        Raises:
            ValidationError: If validation fails.
            FileNotFoundError: If file doesn't exist.
        """
        if not isinstance(file_path, str):
            raise ValidationError("File path must be a non-empty string")

        if not file_path:
            raise ValidationError("File path cannot be empty")

        # Remove leading/trailing whitespace
        file_path = file_path.strip()

        if not file_path:
            raise ValidationError("File path cannot be empty or whitespace only")

        # Check for dangerous patterns FIRST - before checking file existence
        # This ensures security validation happens regardless of file existence
        self._check_dangerous_patterns(file_path)

        # Convert to Path object and resolve
        try:
            path = Path(file_path).resolve()
        except (OSError, ValueError) as e:
            raise ValidationError(f"Invalid file path format: {e}")

        # Check for symlink attacks: reject if the original path is a symlink
        # pointing outside its parent directory
        raw_path = Path(file_path)
        if raw_path.is_symlink():
            link_target = raw_path.resolve()
            link_parent = raw_path.parent.resolve()
            try:
                link_target.relative_to(link_parent)
            except ValueError:
                raise ValidationError(
                    f"Symlink target is outside the parent directory: {file_path}"
                )

        # Additional security check on resolved path
        self._check_dangerous_patterns(str(path))

        # Check if file exists (use os.path for robustness)
        if not os.path.exists(str(path)):
            raise FileNotFoundError(f"Input file not found: {path}")

        # Check if it's actually a file
        if not os.path.isfile(str(path)):
            raise ValidationError(f"Path exists but is not a file: {path}")

        # Check if we can read the file
        if not os.access(path, os.R_OK):
            raise ValidationError(f"File is not readable: {path}")

        # Validate file extension
        self._validate_input_extension(path)

        # Check file size
        self._validate_file_size(path)

        # Validate file format
        self._validate_input_format(path)

        return path

    def validate_output_file_path(self, file_path: str) -> Path:
        """
        Validate and sanitize an output file path.

        Args:
            file_path: Raw output file path string to validate.

        Returns:
            Path: Validated path object.

        Raises:
            ValidationError: If validation fails.
        """
        if not isinstance(file_path, str):
            raise ValidationError("Output file path must be a non-empty string")

        # Remove leading/trailing whitespace
        file_path = file_path.strip()

        if not file_path:
            raise ValidationError("Output file path cannot be empty or whitespace only")

        # Check for dangerous patterns
        self._check_dangerous_patterns(file_path)

        # Convert to Path object and resolve
        try:
            path = Path(file_path).resolve()
        except (OSError, ValueError) as e:
            raise ValidationError(f"Invalid output file path format: {e}")

        # Check parent directory exists and is writable
        parent_dir = path.parent
        if not parent_dir.exists():
            try:
                parent_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise ValidationError(f"Cannot create output directory: {e}")

        if not os.access(parent_dir, os.W_OK):
            raise ValidationError(f"Output directory is not writable: {parent_dir}")

        # Validate output file extension
        self._validate_output_extension(path)

        # Check if file already exists and warn
        if path.exists():
            logger.warning(f"Output file already exists and will be overwritten: {path}")

        return path

    def _check_dangerous_patterns(self, file_path: str) -> None:
        """Check for dangerous patterns in file path."""
        # Check for dangerous Unicode characters (null bytes, BiDi overrides, etc.)
        dangerous_unicode = [
            '\u0000',  # Null byte
            '\u202e',  # Right-to-left override
            '\u202d',  # Left-to-right override
            '\u200f',  # Right-to-left mark
            '\u200e',  # Left-to-right mark
            '\u2066',  # Left-to-right isolate
            '\u2067',  # Right-to-left isolate
            '\u2068',  # First strong isolate
            '\u2069',  # Pop directional isolate
            '\u202a',  # Left-to-right embedding
            '\u202b',  # Right-to-left embedding
            '\u202c',  # Pop directional formatting
        ]
        for char in dangerous_unicode:
            if char in file_path:
                raise ValidationError(f"Potentially dangerous path pattern detected")

        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                raise ValidationError(f"Potentially dangerous path pattern detected")

        # Check for blocked directories (case-insensitive comparison)
        # Also check the original path to catch Windows paths on Unix systems
        abs_path = os.path.abspath(file_path).lower()
        original_path = file_path.lower()

        for blocked_dir in self.BLOCKED_DIRECTORIES:
            blocked_dir_lower = blocked_dir.lower()
            if abs_path.startswith(blocked_dir_lower) or original_path.startswith(blocked_dir_lower):
                raise ValidationError(f"Access to system directory blocked: file not found or not accessible")

    def _validate_input_extension(self, path: Path) -> None:
        """Validate input file extension."""
        if path.suffix.lower() not in {ext.lower() for ext in self.ALLOWED_INPUT_EXTENSIONS}:
            allowed = ', '.join(sorted(self.ALLOWED_INPUT_EXTENSIONS))
            raise ValidationError(
                f"Invalid input file extension '{path.suffix}'. "
                f"Allowed extensions: {allowed}"
            )

    def _validate_output_extension(self, path: Path) -> None:
        """Validate output file extension."""
        if path.suffix.lower() not in {ext.lower() for ext in self.ALLOWED_OUTPUT_EXTENSIONS}:
            allowed = ', '.join(sorted(self.ALLOWED_OUTPUT_EXTENSIONS))
            raise ValidationError(
                f"Invalid output file extension '{path.suffix}'. "
                f"Allowed extensions: {allowed}"
            )

    def _validate_file_size(self, path: Path) -> None:
        """Validate file size constraints."""
        try:
            file_size = path.stat().st_size
        except OSError as e:
            raise ValidationError(f"Cannot determine file size: {e}")

        if file_size < self.MIN_FILE_SIZE_BYTES:
            raise ValidationError(f"File is too small ({file_size} bytes). Minimum: {self.MIN_FILE_SIZE_BYTES} bytes")

        if file_size > self.max_file_size:
            size_mb = file_size / (1024 * 1024)
            max_mb = self.max_file_size / (1024 * 1024)
            raise ValidationError(
                f"File is too large ({size_mb:.1f}MB). Maximum allowed: {max_mb:.1f}MB"
            )

    def _validate_input_format(self, path: Path) -> None:
        """
        Validate input file format by checking file content.

        Args:
            path: File path to validate.

        Raises:
            ValidationError: If format validation fails.
        """
        try:
            # Check MIME type
            mime_type, _ = mimetypes.guess_type(str(path))
            if mime_type and not any(xml_type in mime_type for xml_type in ['xml', 'text']):
                logger.warning(f"Unexpected MIME type '{mime_type}' for file: {path}")

            # Read first few bytes to check for XML declaration
            with open(path, 'rb') as f:
                header = f.read(1024)  # Read first 1KB

            # Check for known binary file signatures (magic bytes)
            binary_signatures = [
                b'\x89PNG',      # PNG
                b'GIF8',         # GIF
                b'\xff\xd8\xff', # JPEG
                b'PK',           # ZIP/XLSX/DOCX
                b'\x7fELF',      # ELF executable
                b'MZ',           # Windows executable
                b'\x00\x00\x01\x00',  # ICO
                b'%PDF',         # PDF
            ]
            for sig in binary_signatures:
                if header[:len(sig)] == sig:
                    raise ValidationError(f"File appears to contain binary data, expected XML: {path}")

            # Validate UTF-8 encoding
            try:
                header.decode('utf-8')
            except UnicodeDecodeError:
                raise ValidationError(f"File encoding is not valid UTF-8: {path}")

            # Check for XML declaration or root elements
            header_str = header.decode('utf-8', errors='ignore').lower()

            # Look for XML indicators
            xml_indicators = [
                '<?xml',
                '<document',
                'xmlns',
                'camt.053',
                'pain.001',
                'iso:std:iso:20022'
            ]

            has_xml_indicator = any(indicator in header_str for indicator in xml_indicators)

            if not has_xml_indicator:
                # Check if it's binary data (control chars other than whitespace)
                if any(c < 32 and c not in (9, 10, 13) for c in header[:100]):
                    raise ValidationError(f"File appears to contain binary data, expected XML: {path}")
                else:
                    logger.warning(f"File may not be a valid XML document: {path}")

        except UnicodeDecodeError:
            raise ValidationError(f"File encoding is not valid UTF-8: {path}")
        except OSError as e:
            raise ValidationError(f"Cannot read file for format validation: {e}")

    def get_safe_filename(self, filename: str) -> str:
        """
        Generate a safe filename by removing/replacing dangerous characters.

        Args:
            filename: Original filename.

        Returns:
            str: Safe filename.
        """
        # Remove or replace dangerous characters
        safe_chars = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)

        # Remove leading/trailing dots and spaces
        safe_chars = safe_chars.strip('. ')

        # Ensure filename is not empty
        if not safe_chars:
            safe_chars = 'unnamed_file'

        # Truncate if too long (keeping extension)
        if len(safe_chars) > 255:
            name, ext = os.path.splitext(safe_chars)
            safe_chars = name[:255 - len(ext)] + ext

        return safe_chars