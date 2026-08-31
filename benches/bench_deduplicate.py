#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sebastien Rousseau <sebastian.rousseau@gmail.com>
# SPDX-License-Identifier: Apache-2.0 OR MIT
"""What deduplication costs, and the one input shape that hurts.

Deduplication is where a statement tool quietly becomes unusable. It is
the step whose cost depends not on how much data you have but on how
*similar* that data is, and the difference between those two is the
difference between a job that finishes and one that does not.

Two axes are measured, and they behave differently.

* **Total transactions.** Linear, and unremarkable: roughly 15 us per
  transaction whether the batch is five hundred or eight thousand. Read
  ``us/txn`` -- flat is what you want and what you get.

* **The size of the largest duplicate group.** Quadratic. Hold the batch
  at a fixed size and grow only the number of *identical* transactions
  inside it, and cost rises with the square of that group: on the
  measured machine 200 copies inside a 4,000-row batch costs about
  167 ms, and 800 copies costs about 2.76 seconds. Four times the group,
  sixteen times the work.

That is the shape to know about, because it is reachable. A repeated
standing order, a failed batch re-submitted several hundred times, an
export accidentally concatenated with itself -- each produces exactly
this input, and none of them look unusual in a file listing.

The benchmark reports **per-segment exponents** for the group axis rather
than one number across the whole range. A single exponent averages the
quadratic tail together with the flat head where the fixed per-batch cost
still dominates, and comes out near 1.0 -- which reads as linear and is
wrong. The tail is the part that matters.

Run::

    python benches/bench_deduplicate.py
    python benches/bench_deduplicate.py --json
    python benches/bench_deduplicate.py --quick     # what CI runs

Nothing here asserts a threshold: wall-clock is not comparable between
machines, and a flaky performance gate teaches people to ignore red. CI
runs ``--quick`` so a benchmark that has stopped compiling against the
current API fails the build instead of rotting into a file that reads as
verified and is not.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bankstatementparser import Deduplicator


def unique_transactions(count: int, offset: int = 0) -> list[dict]:
    """``count`` transactions that share nothing a matcher would group."""
    return [
        {
            "date": "2026-06-21",
            "amount": f"{((i + offset) % 9000) + 100}.00",
            "currency": "EUR",
            "description": f"Payment {i + offset}",
            "reference": f"REF{i + offset:07d}",
        }
        for i in range(count)
    ]


def with_duplicate_group(total: int, group: int) -> list[dict]:
    """``total`` transactions of which ``group`` are byte-identical.

    The batch size is held constant so the only thing varying is how
    concentrated the duplicates are. Growing both at once would confound
    the two axes and produce an exponent that means nothing.
    """
    duplicated = [
        {
            "date": "2026-06-21",
            "amount": "100.00",
            "currency": "EUR",
            "description": "Duplicated payment",
            "reference": "REF-DUP",
        }
        for _ in range(group)
    ]
    return duplicated + unique_transactions(total - group)


def _time(call) -> float:
    """One warm-up, then the best of three.

    Deduplication at the sizes that matter here runs into seconds, so
    this deliberately does not take many samples: the cost of the
    benchmark would exceed anything it tells you.
    """
    call()
    return min(_once(call) for _ in range(3))


def _once(call) -> float:
    """Measure the duration of a single callable execution in seconds."""
    start = time.perf_counter()
    call()
    return time.perf_counter() - start


def _exponent(a: tuple[int, float], b: tuple[int, float]) -> float | None:
    """Log-log slope between two points: 1.0 linear, 2.0 quadratic."""
    (n0, t0), (n1, t1) = a, b
    if n0 == n1 or t0 <= 0 or t1 <= 0:
        return None
    return math.log(t1 / t0) / math.log(n1 / n0)


def measure_volume(sizes: list[int]) -> dict:
    """Cost against total transaction count, all distinct."""
    dedup = Deduplicator()
    rows, points = [], []
    for count in sizes:
        batch = unique_transactions(count)
        seconds = _time(lambda b=batch: dedup.deduplicate(b))
        points.append((count, seconds))
        rows.append(
            {
                "transactions": count,
                "ms": seconds * 1e3,
                "us_per_txn": seconds * 1e6 / count,
            }
        )
    return {"rows": rows, "exponent": _exponent(points[0], points[-1])}


def measure_group(total: int, groups: list[int]) -> dict:
    """Cost against duplicate-group size, batch size held constant."""
    dedup = Deduplicator()
    rows, points = [], []
    for group in groups:
        batch = with_duplicate_group(total, group)
        seconds = _time(lambda b=batch: dedup.deduplicate(b))
        points.append((group, seconds))
        rows.append({"group": group, "ms": seconds * 1e3})
    segments = [
        {
            "from": points[i][0],
            "to": points[i + 1][0],
            "exponent": _exponent(points[i], points[i + 1]),
        }
        for i in range(len(points) - 1)
    ]
    return {"total": total, "rows": rows, "segments": segments}


def run(quick: bool) -> dict:
    """Measure both axes. ``--quick`` keeps CI under a few seconds."""
    volume_sizes = [500, 2_000] if quick else [500, 2_000, 8_000]
    total = 1_000 if quick else 4_000
    groups = [1, 50, 200] if quick else [1, 10, 50, 200, 800]
    return {
        "volume": measure_volume(volume_sizes),
        "duplicate_group": measure_group(total, groups),
    }


def render(results: dict) -> None:
    """Print both tables and the per-segment verdict."""
    volume = results["volume"]
    print("  Cost against total transactions, all distinct:\n")
    print(f"    {'transactions':>13}{'ms':>10}{'us/txn':>10}")
    for row in volume["rows"]:
        print(
            f"    {row['transactions']:>13}{row['ms']:>10.2f}"
            f"{row['us_per_txn']:>10.2f}"
        )
    exponent = volume["exponent"]
    if exponent is not None:
        shape = "linear" if exponent <= 1.25 else "superlinear"
        print(f"\n    growth exponent {exponent:.2f} -- {shape}.")

    group = results["duplicate_group"]
    print(
        f"\n  Cost against the largest duplicate group, batch held at "
        f"{group['total']:,}:\n"
    )
    print(f"    {'group':>8}{'ms':>12}")
    for row in group["rows"]:
        print(f"    {row['group']:>8}{row['ms']:>12.2f}")

    print("\n    per-segment exponent:")
    for segment in group["segments"]:
        exponent = segment["exponent"]
        if exponent is None:
            continue
        note = ""
        if exponent >= 1.75:
            note = "  <-- quadratic"
        elif exponent < 0.5:
            note = "  (fixed per-batch cost still dominating)"
        print(
            f"      {segment['from']:>5} -> {segment['to']:<5}"
            f"{exponent:>6.2f}{note}"
        )

    tail = [s for s in group["segments"] if s["exponent"] is not None]
    if tail and tail[-1]["exponent"] >= 1.75:
        print(
            "\n    Quadratic in the size of the largest duplicate group. "
            "Four times the group is\n    sixteen times the work, and this "
            "input is reachable: a repeated standing order, a\n    failed "
            "batch re-submitted, an export concatenated with itself. None "
            "of them look\n    unusual in a file listing.\n\n"
            "    Read the segments rather than one exponent across the "
            "range: averaging the tail\n    together with the flat head "
            "gives about 1.0, which reads as linear and is wrong."
        )


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--quick", action="store_true", help="small sizes, as CI runs"
    )
    args = parser.parse_args()

    results = run(quick=args.quick)
    if args.json:
        json.dump(results, sys.stdout, indent=1)
        print()
    else:
        render(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
