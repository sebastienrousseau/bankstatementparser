# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Regression tests for file-backed XML and bounded parallel scheduling."""

from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

import pytest
from lxml import etree

from bankstatementparser import CamtParser, Pain001Parser, iter_files_parallel
from bankstatementparser.parallel import FileResult, parse_files_parallel


def _camt() -> str:
    return (
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">'
        "<Stmt><Acct><Id><IBAN>A</IBAN></Id><Ccy>EUR</Ccy></Acct>"
        '<Ntry><Amt Ccy="EUR">1</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry></Stmt>'
        "<Stmt><Acct><Id><IBAN>B</IBAN></Id><Ccy>USD</Ccy></Acct>"
        '<Ntry><Amt Ccy="USD">2</Amt><CdtDbtInd>DBIT</CdtDbtInd></Ntry></Stmt></Document>'
    )


def _pain() -> str:
    return (
        '<p:Document xmlns:p="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03" xmlns:x="urn:extension">'
        "<p:CstmrCdtTrfInitn><!-- comment --><p:GrpHdr><p:MsgId>M</p:MsgId></p:GrpHdr>"
        + "".join(
            "<p:PmtInf><p:PmtInfId>P</p:PmtInfId><p:DbtrAcct><p:Id><p:IBAN>"
            + account
            + "</p:IBAN></p:Id></p:DbtrAcct>"
            '<p:CdtTrfTxInf><p:Amt><p:InstdAmt Ccy="EUR">1</p:InstdAmt></p:Amt><x:Unknown>ignore</x:Unknown></p:CdtTrfTxInf></p:PmtInf>'
            for account in ("A", "B")
        )
        + "</p:CstmrCdtTrfInitn></p:Document>"
    )


@pytest.mark.parametrize(
    "parser_type,xml", [(CamtParser, _camt()), (Pain001Parser, _pain())]
)
def test_lazy_xml_streams_without_materializing_tree(
    tmp_path: Path, parser_type: type, xml: str
) -> None:
    path = tmp_path / "lazy.xml"
    path.write_text(xml)
    parser = parser_type(str(path), lazy=True)
    assert parser._tree is None
    with patch.object(
        parser, "_load_tree", side_effect=AssertionError("eager loading")
    ):
        records = list(parser.parse_streaming())
        assert len(records) == 2
        assert parser._tree is None
        assert list(parser.parse_streaming()) == records
    assert parser.parse().to_dict("records") == records
    assert parser.tree is parser.tree
    assert parser._tree is not None


@pytest.mark.parametrize(
    "parser_type,xml", [(CamtParser, _camt()), (Pain001Parser, _pain())]
)
def test_lazy_stream_closes_file_when_consumer_stops(
    tmp_path: Path, parser_type: type, xml: str
) -> None:
    path = tmp_path / "close.xml"
    path.write_text(xml)
    parser = parser_type(str(path), lazy=True)
    real_open = open
    opened = []

    def track_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        opened.append(handle)
        return handle

    with patch("builtins.open", track_open):
        stream = parser.parse_streaming()
        next(stream)
        stream.close()
    assert opened
    assert all(handle.closed for handle in opened)


@pytest.mark.parametrize("parser_type", [CamtParser, Pain001Parser])
def test_lazy_xml_reports_malformed_content_on_iteration(
    tmp_path: Path, parser_type: type
) -> None:
    path = tmp_path / "broken.xml"
    path.write_text("<Document><broken></Document>")
    parser = parser_type(str(path), lazy=True)
    with pytest.raises(etree.XMLSyntaxError):
        list(parser.parse_streaming())


def test_lazy_camt_validates_path_objects(tmp_path: Path) -> None:
    path = tmp_path / "path.xml"
    path.write_text(_camt())
    parser = CamtParser(path, lazy=True)
    assert len(list(parser.parse_streaming())) == 2


class _Executor:
    def __init__(self, **kwargs):
        self.submitted = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, fn, name, format_name):
        future = Future()
        future.set_result(
            FileResult(path=name, status=str(len(self.submitted)))
        )
        self.submitted.append(future)
        return future


def test_parallel_window_consumption_order_and_repeated_paths() -> None:
    consumed = []

    def paths():
        for name in ["same.xml", "same.xml", "third.xml", "fourth.xml"]:
            consumed.append(name)
            yield name

    executor = _Executor()
    with patch(
        "bankstatementparser.parallel.ProcessPoolExecutor",
        return_value=executor,
    ):
        stream = iter_files_parallel(paths(), max_workers=1, max_pending=2)
        first = next(stream)
        assert first.status == "0"
        assert len(consumed) == 2
        second = next(stream)
        assert second.status == "1"
        assert len(consumed) == 3
        assert [r.path for r in stream] == ["third.xml", "fourth.xml"]
        assert len(consumed) == 4


def test_parallel_early_close_cancels_queued_work() -> None:
    executor = _Executor()
    with patch(
        "bankstatementparser.parallel.ProcessPoolExecutor",
        return_value=executor,
    ):
        stream = iter_files_parallel(["one", "two", "three"], max_pending=2)
        next(stream)
        queued = executor.submitted[1]
        with patch.object(queued, "cancel", wraps=queued.cancel) as cancel:
            stream.close()
        cancel.assert_called_once()
        assert len(executor.submitted) == 2


@pytest.mark.parametrize("kwargs", [{"max_workers": 0}, {"max_pending": 0}])
def test_parallel_rejects_nonpositive_limits(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="positive"):
        list(iter_files_parallel([], **kwargs))
    with pytest.raises(ValueError, match="positive"):
        parse_files_parallel([], **kwargs)


def test_parallel_cpu_count_unavailable() -> None:
    with patch("bankstatementparser.parallel.os.cpu_count", return_value=None):
        assert list(iter_files_parallel([])) == []
