"""Benchmark regression suite for parser hot paths."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pytest_benchmark")

from bankstatementparser import CamtParser, Pain001Parser


@pytest.fixture(scope="module")
def camt_parser() -> CamtParser:
    path = Path(__file__).parent / "test_data" / "camt.053.001.02.xml"
    return CamtParser(str(path))


@pytest.fixture(scope="module")
def pain001_parser() -> Pain001Parser:
    path = (
        Path(__file__).parent / "test_data" / "pain.001.001.03.xml"
    )
    return Pain001Parser(str(path))


def test_benchmark_camt_parse(
    benchmark: pytest.BenchmarkFixture, camt_parser: CamtParser
) -> None:
    frame = benchmark(camt_parser.parse)
    assert not frame.empty


def test_benchmark_pain001_parse(
    benchmark: pytest.BenchmarkFixture,
    pain001_parser: Pain001Parser,
) -> None:
    frame = benchmark(pain001_parser.parse)
    assert not frame.empty


def test_benchmark_camt_streaming(
    benchmark: pytest.BenchmarkFixture, camt_parser: CamtParser
) -> None:
    rows = benchmark(lambda: list(camt_parser.parse_streaming()))
    assert rows


def test_benchmark_pain001_streaming(
    benchmark: pytest.BenchmarkFixture,
    pain001_parser: Pain001Parser,
) -> None:
    rows = benchmark(lambda: list(pain001_parser.parse_streaming()))
    assert rows
