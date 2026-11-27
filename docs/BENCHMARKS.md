# Benchmarks

Two benchmarks ship in `benches/`. Both print the numbers and, with
`--json`, a machine-readable form; CI runs each with `--quick` on every
change so they keep working against the current API. Neither asserts a
threshold: wall-clock time is not comparable between machines.

The performance contract tests (`tests/test_performance_contracts.py`,
`make test-slow`) are what CI enforces: CAMT.053 streaming above 8,000
transactions per second and PAIN.001 above 2,000, measured under
coverage instrumentation on shared runners, plus a time-to-first-result
bound and parallel scaling.

## Environment

The results below are one run of each benchmark on:

| | |
| :--- | :--- |
| Machine | Apple M1 Pro, 16 GB memory |
| OS | macOS 27.2.1 (arm64) |
| Python | CPython 3.12.16 |
| Package | bankstatementparser 0.0.36, `poetry install --with dev -E excel` |
| Date | 2026-11-27 |

## Streaming parsers

`python benches/bench_streaming.py` streams synthetic files with
`parse_streaming()`, best of three runs after a warm-up. The files come
from the generators the contract tests use.

| Format | Transactions | Transactions/s | µs per transaction | First record |
| :--- | ---: | ---: | ---: | ---: |
| CAMT.053 | 1,000 | 23,772 | 42.1 | 0.73 ms |
| CAMT.053 | 10,000 | 23,273 | 43.0 | 0.93 ms |
| CAMT.053 | 50,000 | 22,757 | 43.9 | 0.89 ms |
| PAIN.001 | 1,000 | 46,423 | 21.5 | 5.35 ms |
| PAIN.001 | 10,000 | 56,311 | 17.8 | 8.00 ms |
| PAIN.001 | 50,000 | 55,669 | 18.0 | 13.43 ms |

Throughput is flat from 1,000 to 50,000 transactions: the cost per
record does not grow with the file. PAIN.001's first record arrives
later on bigger files because a file under 50 MB is read and has its
namespaces stripped in one pass before the first transfer is yielded
(larger files are processed in chunks through a temporary file).

## Deduplication

`python benches/bench_deduplicate.py` measures `Deduplicator` along two
axes; its docstring explains why they are separate.

Cost against the number of transactions, all distinct:

| Transactions | Time | µs per transaction |
| ---: | ---: | ---: |
| 500 | 9.28 ms | 18.55 |
| 2,000 | 37.95 ms | 18.97 |
| 8,000 | 156.07 ms | 19.51 |

Growth exponent 1.02: linear.

Cost against the size of the largest group of identical transactions,
batch held at 4,000:

| Duplicate group | Time |
| ---: | ---: |
| 1 | 81.24 ms |
| 10 | 77.01 ms |
| 50 | 90.09 ms |
| 200 | 225.40 ms |
| 800 | 2,423.87 ms |

Between groups of 200 and 800 the exponent is 1.71: a large group of
byte-identical transactions (a re-submitted batch, a file concatenated
with itself) costs close to quadratic time. Below 50 the fixed
per-batch cost dominates.

## Reproduce

```bash
poetry install --with dev -E excel
poetry run python benches/bench_streaming.py
poetry run python benches/bench_deduplicate.py
poetry run pytest --no-cov -m slow tests/test_performance_contracts.py
```
