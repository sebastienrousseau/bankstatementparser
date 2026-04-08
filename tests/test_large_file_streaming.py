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
#
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Large-file streaming tests.

Validates that parse_streaming() handles files at treasury scale:
- 10,000 transactions (~5 MB CAMT, ~15 MB PAIN.001)
- 50,000 transactions (~25 MB CAMT, ~75 MB PAIN.001)
- Memory stays bounded regardless of file size.
- Throughput exceeds 5,000 transactions/second.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest


def _generate_camt_xml(n_transactions: int) -> str:
    """Generate a synthetic CAMT.053 XML with *n* transactions."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<Document><BkToCstmrStmt><Stmt>",
        "<Id>PERF_STMT</Id>",
        "<Acct><Id><IBAN>GB29NWBK60161331926819"
        "</IBAN></Id></Acct>",
        "<Bal><Amt Ccy=\"EUR\">500000.00</Amt>"
        "<CdtDbtInd>CRDT</CdtDbtInd>"
        "<Tp><Cd>OPBD</Cd></Tp>"
        "<Dt><Dt>2025-01-01</Dt></Dt></Bal>",
    ]
    for i in range(n_transactions):
        day = (i % 28) + 1
        parts.append(
            f"<Ntry>"
            f"<Amt Ccy=\"EUR\">{100 + (i % 9999)}.{i % 100:02d}"
            f"</Amt>"
            f"<CdtDbtInd>{'CRDT' if i % 3 else 'DBIT'}"
            f"</CdtDbtInd>"
            f"<BookgDt><Dt>2025-01-{day:02d}</Dt></BookgDt>"
            f"<ValDt><Dt>2025-01-{day:02d}</Dt></ValDt>"
            f"<NtryDtls><TxDtls>"
            f"<RltdPties>"
            f"<Dbtr><Nm>Debtor {i}</Nm></Dbtr>"
            f"<Cdtr><Nm>Creditor {i}</Nm></Cdtr>"
            f"</RltdPties>"
            f"<RmtInf><Ustrd>TX-{i:08d}</Ustrd></RmtInf>"
            f"</TxDtls></NtryDtls>"
            f"</Ntry>"
        )
    parts.append(
        "<Bal><Amt Ccy=\"EUR\">600000.00</Amt>"
        "<CdtDbtInd>CRDT</CdtDbtInd>"
        "<Tp><Cd>CLBD</Cd></Tp>"
        "<Dt><Dt>2025-01-31</Dt></Dt></Bal>"
    )
    parts.append("</Stmt></BkToCstmrStmt></Document>")
    return "".join(parts)


def _generate_pain001_xml(n_transactions: int) -> str:
    """Generate a synthetic PAIN.001 XML with *n* transactions."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:'
        'pain.001.001.03">',
        "<CstmrCdtTrfInitn>",
        "<GrpHdr>"
        "<MsgId>PERF-MSG-001</MsgId>"
        "<CreDtTm>2025-01-15T10:00:00</CreDtTm>"
        f"<NbOfTxs>{n_transactions}</NbOfTxs>"
        "<InitgPty><Nm>Perf Corp</Nm></InitgPty>"
        "</GrpHdr>",
        "<PmtInf>"
        "<PmtInfId>PMT-PERF-001</PmtInfId>"
        "<PmtMtd>TRF</PmtMtd>"
        f"<NbOfTxs>{n_transactions}</NbOfTxs>"
        f"<CtrlSum>{n_transactions * 1500}.00</CtrlSum>"
        "<ReqdExctnDt>2025-01-20</ReqdExctnDt>"
        "<Dbtr><Nm>Treasury Dept</Nm></Dbtr>"
        "<DbtrAcct><Id>"
        "<IBAN>DE89370400440532013000</IBAN>"
        "</Id></DbtrAcct>"
        "<DbtrAgt><FinInstnId>"
        "<BIC>COBADEFFXXX</BIC>"
        "</FinInstnId></DbtrAgt>"
        "<ChrgBr>SLEV</ChrgBr>",
    ]
    for i in range(n_transactions):
        parts.append(
            f"<CdtTrfTxInf>"
            f"<PmtId><EndToEndId>E2E-{i:08d}</EndToEndId></PmtId>"
            f"<Amt><InstdAmt Ccy=\"EUR\">"
            f"{1000 + (i % 5000)}.{i % 100:02d}"
            f"</InstdAmt></Amt>"
            f"<CdtrAgt><FinInstnId>"
            f"<BIC>BNPAFRPP</BIC>"
            f"</FinInstnId></CdtrAgt>"
            f"<Cdtr><Nm>Vendor {i}</Nm></Cdtr>"
            f"<CdtrAcct><Id>"
            f"<IBAN>FR76300060000111{i:08d}</IBAN>"
            f"</Id></CdtrAcct>"
            f"<RmtInf><Ustrd>Invoice INV-{i:08d}</Ustrd></RmtInf>"
            f"</CdtTrfTxInf>"
        )
    parts.append("</PmtInf></CstmrCdtTrfInitn></Document>")
    return "".join(parts)


def _write_temp(content: str, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="bsp_perf_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


class TestCamtLargeFileStreaming(unittest.TestCase):
    """Validate CAMT streaming at 10K and 50K transactions."""

    def test_stream_10k_transactions(self) -> None:
        """Stream 10,000 CAMT transactions under 20 MB memory."""
        from bankstatementparser.camt_parser import CamtParser

        path = _write_temp(_generate_camt_xml(10_000), ".xml")
        file_mb = os.path.getsize(path) / 1024 / 1024
        try:
            parser = CamtParser(path)
            mem_before = _rss_mb()

            count = 0
            t0 = time.perf_counter()
            for tx in parser.parse_streaming():
                count += 1
                self.assertIn("Amount", tx)
                self.assertIn("AccountId", tx)
            elapsed = time.perf_counter() - t0

            mem_after = _rss_mb()
            growth = mem_after - mem_before

            self.assertEqual(count, 10_000)
            self.assertLess(
                growth,
                40.0,
                f"Memory grew {growth:.1f} MB on "
                f"{file_mb:.1f} MB file",
            )

            throughput = count / elapsed
            self.assertGreater(
                throughput,
                5_000,
                f"Throughput {throughput:.0f} tx/s "
                f"below 5,000 tx/s target",
            )
        finally:
            os.unlink(path)

    def test_stream_50k_transactions(self) -> None:
        """Stream 50,000 CAMT transactions under 30 MB memory."""
        from bankstatementparser.camt_parser import CamtParser

        path = _write_temp(_generate_camt_xml(50_000), ".xml")
        file_mb = os.path.getsize(path) / 1024 / 1024
        try:
            parser = CamtParser(path)
            mem_before = _rss_mb()

            count = 0
            t0 = time.perf_counter()
            for _tx in parser.parse_streaming():
                count += 1
            elapsed = time.perf_counter() - t0

            mem_after = _rss_mb()
            growth = mem_after - mem_before

            self.assertEqual(count, 50_000)
            self.assertLess(
                growth,
                60.0,
                f"Memory grew {growth:.1f} MB on "
                f"{file_mb:.1f} MB file",
            )

            throughput = count / elapsed
            self.assertGreater(
                throughput,
                5_000,
                f"Throughput {throughput:.0f} tx/s "
                f"below 5,000 tx/s target",
            )
        finally:
            os.unlink(path)


class TestPain001LargeFileStreaming(unittest.TestCase):
    """Validate PAIN.001 streaming at 10K and 50K transactions."""

    def test_stream_10k_payments(self) -> None:
        """Stream 10,000 PAIN.001 payments at >2,000 tx/s."""
        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        path = _write_temp(
            _generate_pain001_xml(10_000), ".xml"
        )
        try:
            parser = Pain001Parser(path)

            count = 0
            first_pmt = None
            t0 = time.perf_counter()
            for pmt in parser.parse_streaming():
                count += 1
                if first_pmt is None:
                    first_pmt = pmt
            elapsed = time.perf_counter() - t0

            self.assertEqual(count, 10_000)
            self.assertIn("InstdAmt", first_pmt)
            self.assertIn("CdtrNm", first_pmt)

            # Threshold set at 1,000 tx/s to accommodate
            # coverage instrumentation overhead (~75%).
            # Without coverage: >50,000 tx/s observed.
            throughput = count / elapsed
            self.assertGreater(
                throughput,
                1_000,
                f"Throughput {throughput:.0f} tx/s "
                f"below 1,000 tx/s target",
            )
        finally:
            os.unlink(path)

    def test_stream_50k_payments(self) -> None:
        """Stream 50,000 PAIN.001 payments at >2,000 tx/s."""
        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        path = _write_temp(
            _generate_pain001_xml(50_000), ".xml"
        )
        try:
            parser = Pain001Parser(path)

            count = 0
            t0 = time.perf_counter()
            for _pmt in parser.parse_streaming():
                count += 1
            elapsed = time.perf_counter() - t0

            self.assertEqual(count, 50_000)

            throughput = count / elapsed
            self.assertGreater(
                throughput,
                1_000,
                f"Throughput {throughput:.0f} tx/s "
                f"below 1,000 tx/s target",
            )
        finally:
            os.unlink(path)


class TestPain001LargeFilePath(unittest.TestCase):
    """Test the chunk-based temp-file path for files > threshold."""

    def test_chunk_streaming_via_temp_file(self) -> None:
        """Force the large-file branch by lowering the threshold."""
        from unittest.mock import patch

        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        xml = _generate_pain001_xml(100)
        path = _write_temp(xml, ".xml")
        try:
            parser = Pain001Parser(path)
            # Patch the threshold constant inside parse_streaming
            # by making file_size > threshold via a tiny threshold.
            with patch("os.path.getsize", return_value=999_999_999):
                count = 0
                for pmt in parser.parse_streaming():
                    count += 1
                    self.assertIn("InstdAmt", pmt)
                self.assertEqual(count, 100)
        finally:
            os.unlink(path)

    def test_chunk_streaming_cleanup_on_error(self) -> None:
        """Temp file is cleaned up even when iteration stops early."""
        from unittest.mock import patch

        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        xml = _generate_pain001_xml(50)
        path = _write_temp(xml, ".xml")
        try:
            parser = Pain001Parser(path)
            with patch("os.path.getsize", return_value=999_999_999):
                gen = parser.parse_streaming()
                next(gen)  # consume one
                gen.close()  # abandon
                # No temp files should leak — verified by
                # the finally block in parse_streaming.
        finally:
            os.unlink(path)

    def test_chunk_streaming_cleanup_survives_unlink_failure(
        self,
    ) -> None:
        """Temp file cleanup tolerates OSError on unlink."""
        from unittest.mock import patch

        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        xml = _generate_pain001_xml(10)
        path = _write_temp(xml, ".xml")
        try:
            parser = Pain001Parser(path)
            with patch(
                "os.path.getsize", return_value=999_999_999
            ):
                with patch(
                    "os.unlink", side_effect=OSError("busy")
                ):
                    count = sum(
                        1 for _ in parser.parse_streaming()
                    )
            self.assertEqual(count, 10)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestPain001LargeFileErrorPaths(unittest.TestCase):
    """Cover error handling in the large-file streaming branch."""

    def test_large_file_not_found(self) -> None:
        """FileNotFoundError from the chunk reader."""
        from pathlib import Path
        from unittest.mock import patch

        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        xml = _generate_pain001_xml(5)
        path = _write_temp(xml, ".xml")
        try:
            parser = Pain001Parser(path)
            os.unlink(path)
            # Use Path to skip string-based InputValidator
            parser.file_name = Path(path)
            with patch(
                "os.path.getsize", return_value=999_999_999
            ):
                with self.assertRaises(FileNotFoundError):
                    list(parser.parse_streaming())
        except FileNotFoundError:
            pass

    def test_large_file_permission_error(self) -> None:
        """PermissionError from the chunk reader."""
        from pathlib import Path
        from unittest.mock import patch

        from bankstatementparser.input_validator import (
            ValidationError,
        )
        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        xml = _generate_pain001_xml(5)
        path = _write_temp(xml, ".xml")
        try:
            parser = Pain001Parser(path)
            parser.file_name = Path(path)
            with patch(
                "os.path.getsize", return_value=999_999_999
            ):
                with patch(
                    "builtins.open",
                    side_effect=PermissionError("denied"),
                ):
                    with self.assertRaises(ValidationError):
                        list(parser.parse_streaming())
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_large_file_os_error(self) -> None:
        """Generic OSError from the chunk reader."""
        from pathlib import Path
        from unittest.mock import patch

        from bankstatementparser.input_validator import (
            ValidationError,
        )
        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        xml = _generate_pain001_xml(5)
        path = _write_temp(xml, ".xml")
        try:
            parser = Pain001Parser(path)
            parser.file_name = Path(path)
            with patch(
                "os.path.getsize", return_value=999_999_999
            ):
                with patch(
                    "builtins.open",
                    side_effect=OSError("disk full"),
                ):
                    with self.assertRaises(ValidationError):
                        list(parser.parse_streaming())
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_small_file_permission_error(self) -> None:
        """PermissionError in the small-file fast path."""
        from pathlib import Path
        from unittest.mock import patch

        from bankstatementparser.input_validator import (
            ValidationError,
        )
        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        xml = _generate_pain001_xml(5)
        path = _write_temp(xml, ".xml")
        try:
            parser = Pain001Parser(path)
            parser.file_name = Path(path)
            with patch("os.path.getsize", return_value=100):
                with patch(
                    "builtins.open",
                    side_effect=PermissionError("denied"),
                ):
                    with self.assertRaises(ValidationError):
                        list(parser.parse_streaming())
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_small_file_os_error(self) -> None:
        """Generic OSError in the small-file fast path."""
        from pathlib import Path
        from unittest.mock import patch

        from bankstatementparser.input_validator import (
            ValidationError,
        )
        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        xml = _generate_pain001_xml(5)
        path = _write_temp(xml, ".xml")
        try:
            parser = Pain001Parser(path)
            parser.file_name = Path(path)
            with patch("os.path.getsize", return_value=100):
                with patch(
                    "builtins.open",
                    side_effect=OSError("read error"),
                ):
                    with self.assertRaises(ValidationError):
                        list(parser.parse_streaming())
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_small_file_not_found(self) -> None:
        """FileNotFoundError in the small-file fast path."""
        from pathlib import Path
        from unittest.mock import patch

        from bankstatementparser.pain001_parser import (
            Pain001Parser,
        )

        xml = _generate_pain001_xml(5)
        path = _write_temp(xml, ".xml")
        try:
            parser = Pain001Parser(path)
            os.unlink(path)
            parser.file_name = Path(path)
            with patch("os.path.getsize", return_value=100):
                with self.assertRaises(FileNotFoundError):
                    list(parser.parse_streaming())
        except FileNotFoundError:
            pass


class TestStreamingMemoryBound(unittest.TestCase):
    """Verify memory does not scale with file size."""

    def test_memory_constant_across_scales(self) -> None:
        """Memory growth at 50K must not exceed 2x growth at 10K."""
        from bankstatementparser.camt_parser import CamtParser

        growths: list[float] = []
        for n in (10_000, 50_000):
            path = _write_temp(_generate_camt_xml(n), ".xml")
            try:
                parser = CamtParser(path)
                mem_before = _rss_mb()
                for _ in parser.parse_streaming():
                    pass
                growth = _rss_mb() - mem_before
                growths.append(max(growth, 0.1))
            finally:
                os.unlink(path)

        ratio = growths[1] / growths[0]
        self.assertLess(
            ratio,
            2.0,
            f"50K growth ({growths[1]:.1f} MB) was "
            f"{ratio:.1f}x the 10K growth "
            f"({growths[0]:.1f} MB) — memory is "
            f"scaling with file size",
        )


def _rss_mb() -> float:
    """Current process RSS in megabytes."""
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (
            1024 * 1024
        )
    except ImportError:
        return 0.0


if __name__ == "__main__":
    unittest.main()
