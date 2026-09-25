#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Smoke-test an installed wheel under an isolated Python interpreter."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.resources
import os
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.testclient import TestClient

import bankstatementparser as bsp
from bankstatementparser.api import create_app


def verify(expected_version: str) -> None:
    """Check packaged metadata, financial output, Parquet and real API workers."""
    installed_path = Path(bsp.__file__).resolve()
    if not installed_path.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError(
            f"Package is not installed in this environment: {installed_path}"
        )
    if (
        bsp.__version__ != expected_version
        or importlib.metadata.version("bankstatementparser")
        != expected_version
    ):
        raise RuntimeError(
            "Installed package version does not match the intended build"
        )
    if (
        not importlib.resources.files("bankstatementparser")
        .joinpath("py.typed")
        .is_file()
    ):
        raise RuntimeError("Wheel is missing its PEP 561 marker")
    with tempfile.TemporaryDirectory(prefix="bsp_wheel_smoke_") as directory:
        root = Path(directory)
        source = root / "statement.csv"
        source.write_text(
            "date,amount,currency,account\n2026-01-01,1.234,KWD,0001\n"
        )
        parser = bsp.CsvStatementParser(source)
        row = parser.parse().iloc[0]
        if row["amount"] != Decimal("1.234") or row["account_id"] != "0001":
            raise RuntimeError(
                "Installed CSV parser lost financial precision or identity"
            )
        schema = pa.schema(
            [
                pa.field("amount", pa.decimal128(38, 3)),
                pa.field("date", pa.date32()),
            ]
        )
        output = root / "statement.parquet"
        rows = [{"amount": Decimal("1.234"), "date": date(2026, 1, 1)}]
        bsp.export_parquet_stream(rows, output, schema=schema, batch_size=1)
        if pq.read_table(output).to_pylist() != rows:
            raise RuntimeError(
                "Installed Parquet export failed its typed round trip"
            )
        xml = root / "statement.xml"
        xml.write_text(
            '<Document><Stmt><Ntry><Amt Ccy="KWD">1.234</Amt><CdtDbtInd>CRDT</CdtDbtInd></Ntry></Stmt></Document>'
        )
        camt = bsp.CamtParser(xml, lazy=True)
        if next(camt.parse_streaming())["Amount"] != Decimal("1.234"):
            raise RuntimeError(
                "Installed lazy CAMT parser returned the wrong amount"
            )
        # A worker must load the installed distribution even when the server's
        # working directory contains a shadow module with the same name.
        (root / "bankstatementparser.py").write_text(
            'raise RuntimeError("working directory shadowed installed wheel")\n'
        )
        original_directory = Path.cwd()
        try:
            os.chdir(root)
            with TestClient(create_app()) as client:
                if client.get("/health").json()["version"] != expected_version:
                    raise RuntimeError(
                        "Installed API reports an unexpected version"
                    )
                response = client.post(
                    "/ingest",
                    files={"file": ("statement.csv", source.read_bytes())},
                )
                if (
                    response.status_code != 200
                    or response.json()["transaction_count"] != 1
                ):
                    raise RuntimeError(
                        f"Installed API subprocess ingestion failed: {response.text}"
                    )
        finally:
            os.chdir(original_directory)
    print(f"Installed wheel smoke passed: {installed_path}")


def main() -> None:
    """Validate an installed artifact against the caller's intended version."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    verify(args.expected_version)


if __name__ == "__main__":
    main()
