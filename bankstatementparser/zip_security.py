"""Secure helpers for reading XML statement files from ZIP archives."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile, ZipInfo

from .input_validator import InputValidator, ValidationError


@dataclass(frozen=True)
class ZipXMLSource:
    """Validated XML payload extracted from a ZIP archive."""

    source_name: str
    xml_bytes: bytes


class ZipSecurityError(ValidationError):
    """Raised when a ZIP archive or ZIP member violates security policy."""


def iter_secure_xml_entries(
    zip_path: str | Path,
    *,
    max_entry_size: int = 10 * 1024 * 1024,
    max_total_uncompressed_size: int = 50 * 1024 * 1024,
    max_compression_ratio: float = 100.0,
) -> Generator[ZipXMLSource, None, None]:
    """Yield validated XML members from a ZIP archive.

    This helper is intentionally strict because ZIP archives may come from
    untrusted banks, middleware, or user uploads.
    """
    if max_entry_size <= 0:
        raise ZipSecurityError("max_entry_size must be greater than zero")
    if max_total_uncompressed_size <= 0:
        raise ZipSecurityError(
            "max_total_uncompressed_size must be greater than zero"
        )
    if max_compression_ratio <= 0:
        raise ZipSecurityError(
            "max_compression_ratio must be greater than zero"
        )

    archive_path = Path(zip_path)
    total_uncompressed_size = 0
    validator = InputValidator(max_file_size=max_entry_size)

    try:
        with ZipFile(archive_path) as zf:
            members = zf.infolist()
            if not members:
                raise ZipSecurityError(
                    "ZIP archive does not contain any entries"
                )

            for member in members:
                if member.is_dir():
                    continue
                if not member.filename.lower().endswith(".xml"):
                    continue

                _validate_zip_member(
                    member,
                    max_entry_size=max_entry_size,
                    max_compression_ratio=max_compression_ratio,
                )

                total_uncompressed_size += member.file_size
                if total_uncompressed_size > max_total_uncompressed_size:
                    raise ZipSecurityError(
                        "ZIP archive exceeds the total allowed uncompressed XML size"
                    )

                xml_bytes = zf.read(member)
                try:
                    (
                        xml_bytes,
                        safe_name,
                    ) = validator.validate_xml_content(
                        xml_bytes, source_name=member.filename
                    )
                except ValidationError as exc:
                    raise ZipSecurityError(str(exc)) from exc
                yield ZipXMLSource(
                    source_name=safe_name,
                    xml_bytes=xml_bytes,
                )
    except BadZipFile as exc:
        raise ZipSecurityError(f"Invalid ZIP archive: {archive_path}") from exc


def _validate_zip_member(
    member: ZipInfo,
    *,
    max_entry_size: int,
    max_compression_ratio: float,
) -> None:
    """Validate a ZIP member before it is read into memory."""
    validator = InputValidator()
    safe_name = validator.sanitize_source_name(member.filename)

    if member.flag_bits & 0x1:
        raise ZipSecurityError(
            f"Encrypted ZIP entries are not supported: {safe_name}"
        )

    if member.file_size <= 0:
        raise ZipSecurityError(f"ZIP entry is empty or invalid: {safe_name}")

    if member.file_size > max_entry_size:
        raise ZipSecurityError(
            f"ZIP entry exceeds the allowed uncompressed size limit: {safe_name}"
        )

    compressed_size = member.compress_size
    if compressed_size <= 0:
        raise ZipSecurityError(
            f"ZIP entry has an invalid compressed size: {safe_name}"
        )

    compression_ratio = member.file_size / compressed_size
    if compression_ratio > max_compression_ratio:
        raise ZipSecurityError(
            f"ZIP entry compression ratio exceeds the allowed limit: {safe_name}"
        )
