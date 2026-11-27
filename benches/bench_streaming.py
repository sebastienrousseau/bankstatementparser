"""Streaming throughput of the CAMT.053 and PAIN.001 parsers.

``parse_streaming()`` is the path for large files: it yields one record
at a time with bounded memory. This measures records per second and
time to the first record for synthetic files of 1,000 to 50,000
transactions, built by the same generators the performance-contract
tests use (``tests/test_performance_contracts.py``), so the numbers
here and the CI thresholds there describe the same inputs.

The contract tests assert floors under coverage instrumentation on
shared runners (8,000 tx/s CAMT, 2,000 tx/s PAIN.001). This reports
what an uninstrumented run achieves; flat ``tx/s`` across sizes is the
bounded-memory streaming working as intended.

Run::

    python benches/bench_streaming.py
    python benches/bench_streaming.py --json
    python benches/bench_streaming.py --quick     # what CI runs

Nothing here asserts a threshold: wall-clock is not comparable between
machines. CI runs ``--quick`` so the benchmark cannot rot against the
current API.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_performance_contracts import _gen_camt, _gen_pain

from bankstatementparser import CamtParser, Pain001Parser

FORMATS: dict[str, tuple[Callable[[int], str], type]] = {
    "camt053": (_gen_camt, CamtParser),
    "pain001": (_gen_pain, Pain001Parser),
}


def _measure_file(path: str, parser_cls: type) -> tuple[int, float, float]:
    """Stream ``path`` once: (records, total seconds, first-record ms)."""
    parser = parser_cls(path)
    start = time.perf_counter()
    first = 0.0
    count = 0
    for _ in parser.parse_streaming():
        if count == 0:
            first = time.perf_counter() - start
        count += 1
    return count, time.perf_counter() - start, first * 1e3


def measure(name: str, sizes: list[int]) -> list[dict]:
    """Best of three streaming runs per size for one format."""
    generate, parser_cls = FORMATS[name]
    rows = []
    for size in sizes:
        fd, path = tempfile.mkstemp(suffix=".xml")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(generate(size))
        try:
            _measure_file(path, parser_cls)  # warm-up
            runs = [_measure_file(path, parser_cls) for _ in range(3)]
        finally:
            os.unlink(path)
        count, seconds, first_ms = min(runs, key=lambda r: r[1])
        rows.append(
            {
                "transactions": count,
                "tx_per_s": count / seconds,
                "us_per_tx": seconds * 1e6 / count,
                "first_record_ms": first_ms,
            }
        )
    return rows


def environment() -> dict:
    """Where the numbers came from."""
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(terse=True),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
    }


def run(quick: bool) -> dict:
    """Measure both formats. ``--quick`` keeps CI under a few seconds."""
    sizes = [1_000] if quick else [1_000, 10_000, 50_000]
    return {
        "environment": environment(),
        "results": {name: measure(name, sizes) for name in FORMATS},
    }


def render(results: dict) -> None:
    """Print one table per format."""
    env = results["environment"]
    print(
        f"  {env['implementation']} {env['python']} on {env['platform']}"
        f" ({env['machine']})\n"
    )
    for name, rows in results["results"].items():
        print(f"  {name}:")
        print(
            f"    {'transactions':>13}{'tx/s':>10}{'us/tx':>8}{'first ms':>10}"
        )
        for row in rows:
            print(
                f"    {row['transactions']:>13}{row['tx_per_s']:>10.0f}"
                f"{row['us_per_tx']:>8.1f}{row['first_record_ms']:>10.2f}"
            )
        print()


def main() -> int:
    """Parse the options, measure, and print a table or JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="CI smoke run")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()
    results = run(args.quick)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        render(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
