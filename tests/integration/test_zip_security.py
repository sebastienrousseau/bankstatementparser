"""
Threat-focused integration tests for ZIP ingestion.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from bankstatementparser import CamtParser, iter_secure_xml_entries
from bankstatementparser.zip_security import (
    ZipSecurityError,
    _validate_zip_member,
)

CAMT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt>
    <Stmt>
      <Id>ZIP001</Id>
      <Acct><Id><IBAN>DE89370400440532013000</IBAN></Id></Acct>
      <Ntry>
        <Amt Ccy="EUR">100.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <ValDt><Dt>2024-01-01</Dt></ValDt>
        <BookgDt><Dt>2024-01-01</Dt></BookgDt>
      </Ntry>
    </Stmt>
  </BkToCstmrStmt>
</Document>
"""


class TestZipSecurity:
    @pytest.fixture
    def temp_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "archive.zip"

    def test_secure_zip_xml_iteration_and_parse(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_STORED) as zf:
            zf.writestr("nested/statement.xml", CAMT_XML)
            zf.writestr("nested/readme.txt", "ignore me")

        entries = list(iter_secure_xml_entries(temp_zip))
        assert len(entries) == 1
        parser = CamtParser.from_bytes(
            entries[0].xml_bytes,
            source_name=entries[0].source_name,
        )
        assert not parser.parse().empty

    def test_rejects_invalid_archive(self, temp_zip):
        temp_zip.write_bytes(b"not a zip")
        with pytest.raises(ZipSecurityError, match="Invalid ZIP archive"):
            list(iter_secure_xml_entries(temp_zip))

    def test_rejects_invalid_security_threshold_arguments(self, temp_zip):
        with pytest.raises(ZipSecurityError, match="max_entry_size"):
            list(iter_secure_xml_entries(temp_zip, max_entry_size=0))
        with pytest.raises(
            ZipSecurityError, match="max_total_uncompressed_size"
        ):
            list(
                iter_secure_xml_entries(
                    temp_zip, max_total_uncompressed_size=0
                )
            )
        with pytest.raises(ZipSecurityError, match="max_compression_ratio"):
            list(iter_secure_xml_entries(temp_zip, max_compression_ratio=0))

    def test_rejects_empty_archive(self, temp_zip):
        with ZipFile(temp_zip, "w"):
            pass
        with pytest.raises(
            ZipSecurityError, match="does not contain any entries"
        ):
            list(iter_secure_xml_entries(temp_zip))

    def test_skips_directory_and_non_xml_members(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_STORED) as zf:
            zf.writestr("folder/", "")
            zf.writestr("folder/readme.txt", "hello")
            zf.writestr("folder/statement.xml", CAMT_XML)

        entries = list(iter_secure_xml_entries(temp_zip))
        assert len(entries) == 1
        assert entries[0].source_name == "folder/statement.xml"

    def test_rejects_encrypted_member(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_STORED) as zf:
            zf.writestr("statement.xml", CAMT_XML)

        with ZipFile(temp_zip) as zf:
            encrypted_member = zf.infolist()[0]
            encrypted_member.flag_bits |= 0x1
            with pytest.raises(
                ZipSecurityError, match="Encrypted ZIP entries"
            ):
                _validate_zip_member(
                    encrypted_member,
                    max_entry_size=10 * 1024 * 1024,
                    max_compression_ratio=100.0,
                )

    def test_rejects_oversized_member(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_STORED) as zf:
            zf.writestr("statement.xml", CAMT_XML)

        with pytest.raises(ZipSecurityError, match="uncompressed size limit"):
            list(iter_secure_xml_entries(temp_zip, max_entry_size=100))

    def test_rejects_total_uncompressed_limit(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_STORED) as zf:
            zf.writestr("a.xml", CAMT_XML)
            zf.writestr("b.xml", CAMT_XML)

        with pytest.raises(
            ZipSecurityError,
            match="total allowed uncompressed XML size",
        ):
            list(
                iter_secure_xml_entries(
                    temp_zip, max_total_uncompressed_size=300
                )
            )

    def test_rejects_extreme_compression_ratio(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_DEFLATED) as zf:
            zf.writestr(
                "statement.xml",
                "<?xml version='1.0'?><Document>"
                + ("A" * 50000)
                + "</Document>",
            )

        with pytest.raises(
            ZipSecurityError, match="compression ratio exceeds"
        ):
            list(iter_secure_xml_entries(temp_zip, max_compression_ratio=2.0))

    def test_rejects_invalid_member_sizes(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_STORED) as zf:
            zf.writestr("statement.xml", CAMT_XML)

        with ZipFile(temp_zip) as zf:
            invalid_member = zf.infolist()[0]
            invalid_member.file_size = 0
            with pytest.raises(ZipSecurityError, match="empty or invalid"):
                _validate_zip_member(
                    invalid_member,
                    max_entry_size=10 * 1024 * 1024,
                    max_compression_ratio=100.0,
                )

    def test_rejects_invalid_compressed_size(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_STORED) as zf:
            zf.writestr("statement.xml", CAMT_XML)

        with ZipFile(temp_zip) as zf:
            invalid_member = zf.infolist()[0]
            invalid_member.compress_size = 0
            with pytest.raises(
                ZipSecurityError, match="invalid compressed size"
            ):
                _validate_zip_member(
                    invalid_member,
                    max_entry_size=10 * 1024 * 1024,
                    max_compression_ratio=100.0,
                )

    def test_rejects_member_with_binary_xml_payload(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_STORED) as zf:
            zf.writestr("statement.xml", b"%PDF-1.7")

        with pytest.raises(ZipSecurityError, match="binary data"):
            list(iter_secure_xml_entries(temp_zip))

    def test_sanitizes_member_name_for_diagnostics(self, temp_zip):
        with ZipFile(temp_zip, "w", compression=ZIP_STORED) as zf:
            zf.writestr("evil\u202ename.xml", CAMT_XML)

        entries = list(iter_secure_xml_entries(temp_zip))
        assert entries[0].source_name == "evil?name.xml"
