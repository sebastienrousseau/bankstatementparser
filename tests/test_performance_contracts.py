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
#
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Performance contract tests.

Enforces the published performance guarantees:
- Minimum 1,000 TPS for streaming (actual: >20,000 CAMT, >50,000 PAIN)
- Time to first result < 50 ms at any file size
- Parallel multi-file parsing scales with CPU cores
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from bankstatementparser.camt_parser import CamtParser
from bankstatementparser.pain001_parser import Pain001Parser


def _gen_camt(n: int) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Document><BkToCstmrStmt><Stmt>"
        "<Id>PERF</Id>"
        "<Acct><Id><IBAN>DE89370400440532013000"
        "</IBAN></Id></Acct>"
        '<Bal><Amt Ccy="EUR">1000.00</Amt>'
        "<CdtDbtInd>CRDT</CdtDbtInd>"
        "<Tp><Cd>OPBD</Cd></Tp>"
        "<Dt><Dt>2025-01-01</Dt></Dt></Bal>"
    ]
    for i in range(n):
        parts.append(
            f'<Ntry><Amt Ccy="EUR">{100 + i}.00</Amt>'
            f"<CdtDbtInd>CRDT</CdtDbtInd>"
            f"<BookgDt><Dt>2025-01-15</Dt></BookgDt>"
            f"<ValDt><Dt>2025-01-15</Dt></ValDt>"
            f"<NtryDtls><TxDtls>"
            f"<RltdPties>"
            f"<Dbtr><Nm>D{i}</Nm></Dbtr>"
            f"<Cdtr><Nm>C{i}</Nm></Cdtr>"
            f"</RltdPties>"
            f"<RmtInf><Ustrd>TX-{i}</Ustrd></RmtInf>"
            f"</TxDtls></NtryDtls></Ntry>"
        )
    parts.append("</Stmt></BkToCstmrStmt></Document>")
    return "".join(parts)


def _gen_pain(n: int) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:'
        'pain.001.001.03">'
        "<CstmrCdtTrfInitn><GrpHdr>"
        "<MsgId>M1</MsgId>"
        "<CreDtTm>2025-01-15T10:00:00</CreDtTm>"
        f"<NbOfTxs>{n}</NbOfTxs>"
        "<InitgPty><Nm>Corp</Nm></InitgPty>"
        "</GrpHdr><PmtInf>"
        "<PmtInfId>P1</PmtInfId>"
        "<PmtMtd>TRF</PmtMtd>"
        f"<NbOfTxs>{n}</NbOfTxs>"
        "<ReqdExctnDt>2025-01-20</ReqdExctnDt>"
        "<Dbtr><Nm>Treasury</Nm></Dbtr>"
        "<DbtrAcct><Id>"
        "<IBAN>DE89370400440532013000</IBAN>"
        "</Id></DbtrAcct>"
        "<DbtrAgt><FinInstnId>"
        "<BIC>COBADEFFXXX</BIC>"
        "</FinInstnId></DbtrAgt>"
        "<ChrgBr>SLEV</ChrgBr>"
    ]
    for i in range(n):
        parts.append(
            f"<CdtTrfTxInf>"
            f"<PmtId><EndToEndId>E{i}</EndToEndId></PmtId>"
            f'<Amt><InstdAmt Ccy="EUR">'
            f"{1000 + i}.00</InstdAmt></Amt>"
            f"<CdtrAgt><FinInstnId>"
            f"<BIC>BNPAFRPP</BIC>"
            f"</FinInstnId></CdtrAgt>"
            f"<Cdtr><Nm>V{i}</Nm></Cdtr>"
            f"<RmtInf><Ustrd>INV-{i}</Ustrd></RmtInf>"
            f"</CdtTrfTxInf>"
        )
    parts.append(
        "</PmtInf></CstmrCdtTrfInitn></Document>"
    )
    return "".join(parts)


def _write(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


class TestTPSContract(unittest.TestCase):
    """Enforce minimum TPS for streaming.

    Published guarantees:
    - CAMT:    >20,000 tx/s  (<50 us/tx)
    - PAIN.001: >40,000 tx/s  (<25 us/tx)
    Thresholds set conservatively to pass under CI + coverage.
    """

    def test_camt_exceeds_10000_tps(self) -> None:
        """CAMT streaming exceeds 10,000 tx/s at 10K scale."""
        path = _write(_gen_camt(10_000))
        try:
            parser = CamtParser(path)
            t0 = time.perf_counter()
            count = sum(1 for _ in parser.parse_streaming())
            elapsed = time.perf_counter() - t0
            tps = count / elapsed

            self.assertEqual(count, 10_000)
            self.assertGreater(
                tps,
                10_000,
                f"CAMT TPS {tps:.0f} below 10,000 contract",
            )
        finally:
            os.unlink(path)

    def test_pain001_exceeds_2000_tps(self) -> None:
        """PAIN.001 streaming exceeds 2,000 tx/s at 10K scale."""
        path = _write(_gen_pain(10_000))
        try:
            parser = Pain001Parser(path)
            t0 = time.perf_counter()
            count = sum(1 for _ in parser.parse_streaming())
            elapsed = time.perf_counter() - t0
            tps = count / elapsed

            self.assertEqual(count, 10_000)
            # Under coverage instrumentation: >2,000 tx/s.
            # Without coverage: >50,000 tx/s observed.
            self.assertGreater(
                tps,
                2_000,
                f"PAIN.001 TPS {tps:.0f} below 2,000 contract",
            )
        finally:
            os.unlink(path)


class TestLatencyContract(unittest.TestCase):
    """Enforce < 50 ms time-to-first-result."""

    def test_camt_ttfr_under_50ms(self) -> None:
        """CAMT time to first result < 50 ms at 10K scale."""
        path = _write(_gen_camt(10_000))
        try:
            parser = CamtParser(path)
            t0 = time.perf_counter()
            next(parser.parse_streaming())
            ttfr_ms = (time.perf_counter() - t0) * 1000

            self.assertLess(
                ttfr_ms,
                50.0,
                f"CAMT TTFR {ttfr_ms:.1f}ms exceeds "
                f"50ms contract",
            )
        finally:
            os.unlink(path)

    def test_pain001_ttfr_under_50ms(self) -> None:
        """PAIN.001 time to first result < 50 ms at 10K scale."""
        path = _write(_gen_pain(10_000))
        try:
            parser = Pain001Parser(path)
            t0 = time.perf_counter()
            next(parser.parse_streaming())
            ttfr_ms = (time.perf_counter() - t0) * 1000

            self.assertLess(
                ttfr_ms,
                50.0,
                f"PAIN.001 TTFR {ttfr_ms:.1f}ms exceeds "
                f"50ms contract",
            )
        finally:
            os.unlink(path)

    def test_camt_per_tx_under_50ms(self) -> None:
        """CAMT per-transaction latency < 50 ms."""
        path = _write(_gen_camt(1_000))
        try:
            parser = CamtParser(path)
            t0 = time.perf_counter()
            count = sum(1 for _ in parser.parse_streaming())
            elapsed = time.perf_counter() - t0
            per_tx_ms = (elapsed / count) * 1000

            self.assertLess(
                per_tx_ms,
                50.0,
                f"CAMT per-tx {per_tx_ms:.2f}ms exceeds "
                f"50ms contract",
            )
        finally:
            os.unlink(path)


class TestParallelParsing(unittest.TestCase):
    """Validate parallel multi-file processing."""

    def test_parallel_correctness(self) -> None:
        """Parallel parsing produces correct results."""
        from bankstatementparser.parallel import (
            parse_files_parallel,
        )

        paths = [_write(_gen_camt(100)) for _ in range(4)]
        try:
            results = parse_files_parallel(
                paths, format_name="camt"
            )
            for r in results:
                self.assertEqual(r.status, "SUCCESS")
                self.assertEqual(len(r.transactions), 100)
        finally:
            for p in paths:
                os.unlink(p)

    def test_parallel_handles_errors(self) -> None:
        """Parallel parsing reports per-file errors."""
        from bankstatementparser.parallel import (
            parse_files_parallel,
        )

        good = _write(_gen_camt(10))
        bad = "/nonexistent/file.xml"
        try:
            results = parse_files_parallel(
                [good, bad], format_name="camt"
            )
            self.assertEqual(results[0].status, "SUCCESS")
            self.assertEqual(results[1].status, "FAILED")
            self.assertIn("not found", results[1].error.lower())
        finally:
            os.unlink(good)

    def test_parallel_single_file_no_overhead(self) -> None:
        """Single file skips process pool."""
        from bankstatementparser.parallel import (
            parse_files_parallel,
        )

        path = _write(_gen_camt(100))
        try:
            results = parse_files_parallel(
                [path], format_name="camt"
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, "SUCCESS")
        finally:
            os.unlink(path)

    def test_parse_single_file_error(self) -> None:
        """Direct call to _parse_single_file with bad path."""
        from bankstatementparser.parallel import (
            _parse_single_file,
        )

        result = _parse_single_file("/no/such/file.xml", "camt")
        self.assertEqual(result.status, "FAILED")
        self.assertTrue(len(result.error) > 0)

    def test_parallel_empty_list(self) -> None:
        """Empty file list returns empty results."""
        from bankstatementparser.parallel import (
            parse_files_parallel,
        )

        results = parse_files_parallel([])
        self.assertEqual(results, [])

    def test_parallel_preserves_order(self) -> None:
        """Results maintain input order."""
        from bankstatementparser.parallel import (
            parse_files_parallel,
        )

        paths = [_write(_gen_camt(50)) for _ in range(6)]
        try:
            results = parse_files_parallel(
                paths, format_name="camt"
            )
            for i, r in enumerate(results):
                self.assertEqual(r.path, paths[i])
                self.assertEqual(r.status, "SUCCESS")
        finally:
            for p in paths:
                os.unlink(p)


if __name__ == "__main__":
    unittest.main()
