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

"""XML content, binary signature, and source label validation engine."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional, Union

from .exceptions import ValidationError

logger = logging.getLogger(__name__)

__all__ = [
    "check_binary_signatures",
    "check_xml_indicators",
    "sanitize_filename",
    "sanitize_source_name",
    "validate_payload_size",
    "validate_xml_bytes_format",
    "validate_xml_content",
]

_MIN_BYTES = 1

_BINARY_SIGNATURES: tuple[bytes, ...] = (
    b"\x89PNG",
    b"GIF8",
    b"\xff\xd8\xff",
    b"PK",
    b"\x7fELF",
    b"MZ",
    b"\x00\x00\x01\x00",
    b"%PDF",
)

_XML_INDICATORS: tuple[str, ...] = (
    "<?xml",
    "<document",
    "xmlns",
    "camt.053",
    "pain.001",
    "iso:std:iso:20022",
)

_MEM_XML_INDICATORS: tuple[str, ...] = (
    "<?xml",
    "<document",
    "xmlns",
    "camt.",
    "iso:std:iso:20022",
)

_DANGEROUS_UNICODE_CHARS: frozenset[str] = frozenset(
    {
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
    }
)


def sanitize_source_name(
    source_name: Optional[str], default: str = "<memory>"
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
    if source_name is None:
        return default

    if not isinstance(source_name, str):
        raise ValidationError("Source name must be a string")

    cleaned = []
    for char in source_name.strip():
        if ord(char) < 32 or char in _DANGEROUS_UNICODE_CHARS:
            cleaned.append("?")
        else:
            cleaned.append(char)

    sanitized = "".join(cleaned)[:255]
    return sanitized or default


def check_binary_signatures(header: bytes, target: Union[Path, str]) -> None:
    """Check for known binary signatures that indicate invalid text formats.

    Args:
        header: Leading byte header of the file or payload.
        target: File path or diagnostics label for error reporting.

    Raises:
        ValidationError: If known binary magic signatures are present.
    """
    for sig in _BINARY_SIGNATURES:
        if header[: len(sig)] == sig:
            target_str = str(target)
            prefix = (
                "XML content"
                if "<memory>" in target_str or not isinstance(target, Path)
                else "File"
            )
            raise ValidationError(
                f"{prefix} appears to contain binary data, expected XML: {target}"
            )


def check_xml_indicators(
    header: bytes, path: Path, log: Optional[logging.Logger] = None
) -> None:
    """Check for XML declaration or common root namespace indicators in file header.

    Args:
        header: Leading byte header of the file.
        path: Validated file path.
        log: Optional logger for emitting diagnostic warnings.

    Raises:
        ValidationError: If non-printable binary characters are found without indicators.
    """
    active_logger = log or logger
    header_str = header.decode("utf-8", errors="ignore").lower()
    if not any(ind in header_str for ind in _XML_INDICATORS):
        if any(c < 32 and c not in (9, 10, 13) for c in header[:100]):
            raise ValidationError(
                f"File appears to contain binary data, expected XML: {path}"
            )
        active_logger.warning(f"File may not be a valid XML document: {path}")


def validate_xml_bytes_format(
    xml_bytes: bytes,
    source_name: str,
    log: Optional[logging.Logger] = None,
) -> None:
    """Validate XML bytes using the same checks applied to file-backed input.

    Args:
        xml_bytes: Raw XML bytes.
        source_name: Sanitized source label for diagnostics.
        log: Optional logger for emitting diagnostic warnings.

    Raises:
        ValidationError: If content is not plausible UTF-8 XML.
    """
    active_logger = log or logger
    header = xml_bytes[:1024]
    check_binary_signatures(header, source_name)

    try:
        header_str = header.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"XML content encoding is not valid UTF-8: {source_name}"
        ) from exc

    header_lower = header_str.lower()
    has_xml_indicator = any(
        indicator in header_lower for indicator in _MEM_XML_INDICATORS
    )

    if not has_xml_indicator:
        if any(byte < 32 and byte not in (9, 10, 13) for byte in header[:100]):
            raise ValidationError(
                f"XML content appears to contain binary data, expected XML: {source_name}"
            )
        active_logger.warning(
            "XML content may not be a valid XML document: %s",
            source_name,
        )


def validate_payload_size(data: bytes, max_file_size: int) -> None:
    """Validate in-memory payload size constraints."""
    payload_size = len(data)
    if payload_size < _MIN_BYTES:
        raise ValidationError(
            f"XML content is too small ({payload_size} bytes). Minimum: {_MIN_BYTES} bytes"
        )
    if payload_size > max_file_size:
        size_mb = payload_size / (1024 * 1024)
        max_mb = max_file_size / (1024 * 1024)
        raise ValidationError(
            f"XML content is too large ({size_mb:.1f}MB). Maximum allowed: {max_mb:.1f}MB"
        )


def validate_xml_content(
    xml_content: Union[str, bytes],
    *,
    max_file_size: int = 100 * 1024 * 1024,
    source_name: Optional[str] = None,
    log: Optional[logging.Logger] = None,
) -> tuple[bytes, str]:
    """Validate in-memory XML content.

    Args:
        xml_content: XML payload as text or bytes.
        max_file_size: Maximum allowed payload size in bytes.
        source_name: Optional source label used for diagnostics only.
        log: Optional logger for diagnostic messages.

    Returns:
        tuple[bytes, str]: UTF-8 XML bytes and sanitized source name.

    Raises:
        ValidationError: If content is unsafe, empty, oversized, or not XML.
    """
    safe_source_name = sanitize_source_name(source_name)

    if isinstance(xml_content, str):
        if not xml_content.strip():
            raise ValidationError("XML content cannot be empty")
        xml_bytes = xml_content.encode("utf-8")
    elif isinstance(xml_content, bytes):
        if not xml_content.strip():
            raise ValidationError("XML content cannot be empty")
        xml_bytes = xml_content
    else:
        raise ValidationError(
            "XML content must be provided as a string or bytes"
        )

    validate_payload_size(xml_bytes, max_file_size)
    validate_xml_bytes_format(xml_bytes, safe_source_name, log=log)

    return xml_bytes, safe_source_name


def sanitize_filename(filename: str) -> str:
    """Generate a safe filename by removing/replacing dangerous characters.

    Args:
        filename: Original filename.

    Returns:
        str: Safe sanitized filename.
    """
    safe_chars = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)
    safe_chars = safe_chars.strip(". ")
    if not safe_chars:
        return "unnamed_file"
    if len(safe_chars) > 255:
        name, ext = os.path.splitext(safe_chars)
        safe_chars = name[: 255 - len(ext)] + ext
    return safe_chars
