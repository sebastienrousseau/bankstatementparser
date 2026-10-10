# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
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

"""Input validation for file paths, sizes, and formats.

Used throughout the bank statement parser to validate user-supplied
paths before any file I/O happens.
"""

import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import ClassVar, Optional, Union

from .exceptions import ValidationError
from .xml_validator import (
    check_binary_signatures,
    check_xml_indicators,
    sanitize_filename,
    sanitize_source_name,
    validate_payload_size,
    validate_xml_bytes_format,
    validate_xml_content,
)

logger = logging.getLogger(__name__)

__all__ = [
    "InputValidator",
    "ValidationError",
    "sanitize_filename",
    "sanitize_source_name",
    "validate_xml_content",
]

_DANGEROUS_UNICODE: tuple[str, ...] = (
    "\u0000",
    "\u202e",
    "\u202d",
    "\u200f",
    "\u200e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
    "\u202a",
    "\u202b",
    "\u202c",
)


class InputValidator:
    """Comprehensive input validator for file operations."""

    # Default configuration
    MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100MB default
    MIN_FILE_SIZE_BYTES = 1  # 1 byte minimum

    # Allowed file extensions for input files
    ALLOWED_INPUT_EXTENSIONS: ClassVar[set[str]] = {
        ".xml",
        ".XML",
        ".csv",
        ".CSV",
        ".ofx",
        ".OFX",
        ".qfx",
        ".QFX",
        ".mt940",
        ".MT940",
        ".sta",
        ".STA",
        ".bai2",
        ".BAI2",
        ".bai",
        ".BAI",
        ".mt942",
        ".MT942",
        ".pdf",
        ".PDF",
        ".json",
        ".JSON",
    }

    # Allowed file extensions for output files
    ALLOWED_OUTPUT_EXTENSIONS: ClassVar[set[str]] = {
        ".csv",
        ".CSV",
        ".xlsx",
        ".XLSX",
        ".xls",
        ".XLS",
        ".json",
        ".JSON",
        ".parquet",
        ".PARQUET",
    }

    # Dangerous path patterns to block
    DANGEROUS_PATTERNS: ClassVar[list[str]] = [
        r"\.\.",  # Directory traversal (catches ../.. and ..\.. patterns)
        r"/\./",  # Hidden directory traversal
        r"~/",  # Home directory shortcuts (can be allowed if needed)
        r"\$\{",  # Variable expansion
        r"%[A-Z_]+%",  # Windows environment variables
    ]

    # System directories to block (platform-specific)
    BLOCKED_DIRECTORIES: ClassVar[set[str]] = {
        # Unix/Linux/macOS
        "/etc",
        "/bin",
        "/sbin",
        "/usr/bin",
        "/usr/sbin",
        "/sys",
        "/proc",
        "/dev",
        "/boot",
        "/root",
        # Windows
        "C:\\Windows",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
        "C:\\System32",
        "C:\\Windows\\System32",
        # macOS specific
        "/System",
        "/Library/System",
        "/private/var/db",
    }

    def __init__(self, max_file_size: Optional[int] = None):
        """Initialize the validator with optional custom configuration.

        Args:
            max_file_size: Maximum allowed file size in bytes.
        """
        self.max_file_size = max_file_size or self.MAX_FILE_SIZE_BYTES

    def validate_input_file_path(self, file_path: str) -> Path:
        """Validate and sanitize an input file path.

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
            raise ValidationError(
                "File path cannot be empty or whitespace only"
            )

        # Check for dangerous patterns FIRST - before checking file existence
        # This ensures security validation happens regardless of file existence
        self._check_dangerous_patterns(file_path)

        # Convert to Path object and resolve
        try:
            path = Path(file_path).resolve()
        except (OSError, ValueError) as e:
            raise ValidationError(f"Invalid file path format: {e}") from e

        # Check for symlink attacks: reject if the original path is a symlink
        # pointing outside its parent directory
        raw_path = Path(file_path)
        if raw_path.is_symlink():
            link_target = raw_path.resolve()
            link_parent = raw_path.parent.resolve()
            try:
                link_target.relative_to(link_parent)
            except ValueError as exc:
                raise ValidationError(
                    f"Symlink target is outside the parent directory: {file_path}"
                ) from exc

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
        """Validate and sanitize an output file path.

        Args:
            file_path: Raw output file path string to validate.

        Returns:
            Path: Validated path object.

        Raises:
            ValidationError: If validation fails.
        """
        if not isinstance(file_path, str):
            raise ValidationError(
                "Output file path must be a non-empty string"
            )

        # Remove leading/trailing whitespace
        file_path = file_path.strip()

        if not file_path:
            raise ValidationError(
                "Output file path cannot be empty or whitespace only"
            )

        # Check for dangerous patterns
        self._check_dangerous_patterns(file_path)

        # Convert to Path object and resolve
        try:
            path = Path(file_path).resolve()
        except (OSError, ValueError) as e:
            raise ValidationError(
                f"Invalid output file path format: {e}"
            ) from e

        # Check parent directory exists and is writable
        parent_dir = path.parent
        if not parent_dir.exists():
            try:
                parent_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise ValidationError(
                    f"Cannot create output directory: {e}"
                ) from e

        if not os.access(parent_dir, os.W_OK):
            raise ValidationError(
                f"Output directory is not writable: {parent_dir}"
            )

        # Validate output file extension
        self._validate_output_extension(path)

        # Check if file already exists and warn
        if path.exists():
            logger.warning(
                f"Output file already exists and will be overwritten: {path}"
            )

        return path

    def sanitize_source_name(
        self, source_name: Optional[str], default: str = "<memory>"
    ) -> str:
        """Sanitize a caller-supplied source name used only for diagnostics.

        Args:
            source_name: Optional caller-provided source identifier.
            default: Fallback label when source_name is empty.

        Returns:
            str: A bounded, log-safe source label.

        Raises:
            ValidationError: If source_name is not a string.
        """
        return sanitize_source_name(source_name, default)

    def validate_xml_content(
        self,
        xml_content: Union[str, bytes],
        *,
        source_name: Optional[str] = None,
    ) -> tuple[bytes, str]:
        """Validate in-memory XML content.

        Args:
            xml_content: XML payload as text or bytes.
            source_name: Optional source label used for diagnostics only.

        Returns:
            tuple[bytes, str]: UTF-8 XML bytes and sanitized source name.

        Raises:
            ValidationError: If content is unsafe, empty, oversized, or not XML.
        """
        return validate_xml_content(
            xml_content,
            max_file_size=self.max_file_size,
            source_name=source_name,
            log=logger,
        )

    def _check_dangerous_patterns(self, file_path: str) -> None:
        """Check for dangerous patterns in file path."""
        # Check for dangerous Unicode characters (null bytes, BiDi overrides, etc.)
        for char in _DANGEROUS_UNICODE:
            if char in file_path:
                raise ValidationError(
                    "Potentially dangerous path pattern detected"
                )

        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                raise ValidationError(
                    "Potentially dangerous path pattern detected"
                )

        # Check for blocked directories (case-insensitive comparison)
        # Also check the original path to catch Windows paths on Unix systems
        abs_path = os.path.abspath(file_path).lower()
        original_path = file_path.lower()

        for blocked_dir in self.BLOCKED_DIRECTORIES:
            blocked_dir_lower = blocked_dir.lower()
            if abs_path.startswith(
                blocked_dir_lower
            ) or original_path.startswith(blocked_dir_lower):
                raise ValidationError(
                    "Access to system directory blocked: file not found or not accessible"
                )

    def _validate_input_extension(self, path: Path) -> None:
        """Validate input file extension."""
        allowed = {ext.lower() for ext in self.ALLOWED_INPUT_EXTENSIONS}
        from .plugins import get_registered_loaders

        for name in get_registered_loaders():
            allowed.add(f".{name.lower()}")

        if path.suffix.lower() not in allowed:
            allowed_str = ", ".join(sorted(self.ALLOWED_INPUT_EXTENSIONS))
            raise ValidationError(
                f"Invalid input file extension '{path.suffix}'. "
                f"Allowed extensions: {allowed_str}"
            )

    def _validate_output_extension(self, path: Path) -> None:
        """Validate output file extension."""
        if path.suffix.lower() not in {
            ext.lower() for ext in self.ALLOWED_OUTPUT_EXTENSIONS
        }:
            allowed = ", ".join(sorted(self.ALLOWED_OUTPUT_EXTENSIONS))
            raise ValidationError(
                f"Invalid output file extension '{path.suffix}'. "
                f"Allowed extensions: {allowed}"
            )

    def _validate_file_size(self, path: Path) -> None:
        """Validate file size constraints."""
        try:
            file_size = path.stat().st_size
        except OSError as e:
            raise ValidationError(f"Cannot determine file size: {e}") from e

        if file_size < self.MIN_FILE_SIZE_BYTES:
            raise ValidationError(
                f"File is too small ({file_size} bytes). Minimum: {self.MIN_FILE_SIZE_BYTES} bytes"
            )

        if file_size > self.max_file_size:
            size_mb = file_size / (1024 * 1024)
            max_mb = self.max_file_size / (1024 * 1024)
            raise ValidationError(
                f"File is too large ({size_mb:.1f}MB). Maximum allowed: {max_mb:.1f}MB"
            )

    def _validate_bytes_size(self, data: bytes) -> None:
        """Validate in-memory payload size constraints."""
        validate_payload_size(data, self.max_file_size)

    def _read_file_header(self, path: Path) -> bytes:
        """Read the initial bytes of a file for format detection."""
        try:
            with open(path, "rb") as f:
                return f.read(1024)
        except (OSError, UnicodeDecodeError) as e:
            raise ValidationError(
                f"Cannot read file for format validation: {e}"
            ) from e

    def _validate_pdf_format(self, path: Path) -> None:
        """Validate that a PDF input begins with the PDF magic signature."""
        header = self._read_file_header(path)
        if not header.startswith(b"%PDF"):
            raise ValidationError(f"File is not a valid PDF document: {path}")

    def _check_binary_signatures(self, header: bytes, path: Path) -> None:
        """Check for known binary signatures that indicate invalid text formats."""
        check_binary_signatures(header, path)

    def _check_xml_indicators(self, header: bytes, path: Path) -> None:
        """Check for XML declaration or common root namespace indicators."""
        check_xml_indicators(header, path, logger)

    def _validate_input_format(self, path: Path) -> None:
        """Validate input file format by checking file content.

        Args:
            path: File path to validate.

        Raises:
            ValidationError: If format validation fails.
        """
        mime_type, _ = mimetypes.guess_type(str(path))
        if mime_type and not any(
            xml_type in mime_type for xml_type in ["xml", "text"]
        ):
            logger.warning(
                f"Unexpected MIME type '{mime_type}' for file: {path}"
            )

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            self._validate_pdf_format(path)
            return

        header = self._read_file_header(path)
        self._check_binary_signatures(header, path)

        try:
            header.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(
                f"File encoding is not valid UTF-8: {path}"
            ) from exc

        if suffix == ".xml":
            self._check_xml_indicators(header, path)

    def _validate_xml_bytes_format(
        self, xml_bytes: bytes, source_name: str
    ) -> None:
        """Validate XML bytes using the same checks applied to file-backed input.

        Args:
            xml_bytes: Raw XML bytes.
            source_name: Sanitized source label for diagnostics.

        Raises:
            ValidationError: If content is not plausible UTF-8 XML.
        """
        validate_xml_bytes_format(xml_bytes, source_name, logger)

    def get_safe_filename(self, filename: str) -> str:
        """Generate a safe filename by removing/replacing dangerous characters.

        Args:
            filename: Original filename.

        Returns:
            str: Safe filename.
        """
        return sanitize_filename(filename)
