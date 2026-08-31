# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Regression suite: every code example in the docs must actually work.

The docs-accuracy tests check that claims in the docs match the
codebase; this module goes further and *executes* the documented
examples themselves:

* Every fenced ``python`` block in README.md, FAQ.md, docs/index.md,
  and docs/MAPPING.md must be classified in ``BLOCK_SPECS`` below.
  Adding a new block to the docs without classifying it fails the
  suite — examples cannot silently rot.
* ``run`` blocks are executed verbatim against the repository
  fixtures (placeholder paths are materialised as real files in a
  temp directory).
* ``imports`` blocks (the ones that need a live LLM) have every
  import statement executed, so a renamed or removed public API
  still fails fast.
* Documented CLI invocations are run as real subprocesses, and every
  ``--flag`` mentioned in a bash block must exist on the CLI parser.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_FILES = ("README.md", "FAQ.md", "docs/index.md", "docs/MAPPING.md")

CAMT_FIXTURE = REPO_ROOT / "tests" / "test_data" / "camt.053.001.02.xml"
PAIN001_FIXTURE = REPO_ROOT / "tests" / "test_data" / "pain.001.001.03.xml"
OFX_FIXTURE = REPO_ROOT / "tests" / "test_data" / "sample.ofx"


def _has(module: str) -> bool:
    return find_spec(module) is not None


# ----------------------------------------------------------------------
# Block extraction
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class DocBlock:
    doc: str
    line: int
    lang: str
    body: str

    @property
    def location(self) -> str:
        return f"{self.doc}:{self.line}"


def _extract_blocks() -> list[DocBlock]:
    blocks: list[DocBlock] = []
    for rel in DOC_FILES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for match in re.finditer(
            r"^```(\w*)\n(.*?)^```", text, re.DOTALL | re.MULTILINE
        ):
            blocks.append(
                DocBlock(
                    doc=rel,
                    line=text[: match.start()].count("\n") + 1,
                    lang=match.group(1),
                    body=match.group(2),
                )
            )
    return blocks


ALL_BLOCKS = _extract_blocks()
PYTHON_BLOCKS = [b for b in ALL_BLOCKS if b.lang == "python"]
BASH_BLOCKS = [b for b in ALL_BLOCKS if b.lang in ("bash", "sh", "console")]


# ----------------------------------------------------------------------
# Classification registry
# ----------------------------------------------------------------------

_COMMON_PREAMBLE = """
from decimal import Decimal
from pathlib import Path
"""

_TRANSACTIONS_PREAMBLE = """
from bankstatementparser import Transaction

transactions = [
    Transaction(amount=Decimal("100.00"), currency="GBP",
                booking_date="2026-01-05", description="SALARY ACME LTD"),
    Transaction(amount=Decimal("-3.20"), currency="GBP",
                booking_date="2026-01-06", description="COFFEE SHOP 0042"),
    Transaction(amount=Decimal("-50.00"), currency="EUR",
                booking_date="2026-01-07", description="HOTEL PARIS"),
]
"""


@dataclass(frozen=True)
class BlockSpec:
    """How to exercise one documented python block.

    ``marker`` is a substring unique to exactly one block across all
    scanned docs; ``files`` maps placeholder paths used in the block to
    real fixture files materialised in the working directory.
    """

    marker: str
    mode: str = "run"  # "run" | "imports"
    files: tuple[tuple[str, Path], ...] = ()
    preamble: str = ""
    requires: tuple[str, ...] = ()
    reason: str = ""  # why a block is imports-only


BLOCK_SPECS: tuple[BlockSpec, ...] = (
    # README — Parse a CAMT.053 statement
    BlockSpec(
        marker='CamtParser("statement.xml")\ntransactions = parser.parse()',
        files=(("statement.xml", CAMT_FIXTURE),),
    ),
    # README — Parse a PAIN.001 payment file
    BlockSpec(
        marker='Pain001Parser("payment.xml")',
        files=(("payment.xml", PAIN001_FIXTURE),),
    ),
    # README — Auto-detect the format
    BlockSpec(
        marker='detect_statement_format("transactions.ofx")',
        files=(("transactions.ofx", OFX_FIXTURE),),
    ),
    # README — Hybrid smart_ingest three-path tour (B and C need a live
    # LLM and a PDF; the deterministic Path A is exercised by
    # tests/test_hybrid_orchestrator.py and the CLI tests below).
    BlockSpec(
        marker='smart_ingest("scan.pdf")',
        mode="imports",
        reason="paths B/C require a live LLM model and PDFs",
    ),
    # README — Parse from memory (from_bytes)
    BlockSpec(
        marker="CamtParser.from_bytes(xml_bytes",
        preamble=(
            "def download_from_sftp() -> bytes:\n"
            f"    return Path({str(CAMT_FIXTURE)!r}).read_bytes()\n"
        ),
    ),
    # README — Parse a ZIP archive securely
    BlockSpec(
        marker='iter_secure_xml_entries("statements.zip")',
        preamble=(
            "import zipfile\n"
            "with zipfile.ZipFile('statements.zip', 'w') as zf:\n"
            f"    zf.writestr('statement-001.xml', "
            f"Path({str(CAMT_FIXTURE)!r}).read_bytes())\n"
        ),
    ),
    # README — PII redaction toggle
    BlockSpec(
        marker="parser.parse_streaming(redact_pii=True)",
        preamble=(
            "from bankstatementparser import CamtParser\n"
            f"parser = CamtParser({str(CAMT_FIXTURE)!r})\n"
        ),
    ),
    # README — Streaming large files
    BlockSpec(
        marker='CamtParser("large_statement.xml")',
        files=(("large_statement.xml", CAMT_FIXTURE),),
        preamble="def process(transaction) -> None:\n    pass\n",
    ),
    # README — Parallel parsing
    BlockSpec(
        marker="parse_files_parallel([",
        files=(
            ("statements/jan.xml", CAMT_FIXTURE),
            ("statements/feb.xml", CAMT_FIXTURE),
            ("statements/mar.xml", CAMT_FIXTURE),
        ),
    ),
    # README — Deduplicator
    BlockSpec(
        marker="dedup.from_dataframe(parser.parse())",
        files=(("statement.xml", CAMT_FIXTURE),),
    ),
    # README — CSV/JSON/Excel exports
    BlockSpec(
        marker='parser.camt_to_excel("output.xlsx")',
        files=(("statement.xml", CAMT_FIXTURE),),
        preamble="from bankstatementparser import CamtParser\n",
        requires=("openpyxl",),
    ),
    # README — Polars conversion
    BlockSpec(
        marker="parser.to_polars_lazy()",
        preamble=(
            "from bankstatementparser import CamtParser\n"
            f"parser = CamtParser({str(CAMT_FIXTURE)!r})\n"
            "parser.parse()\n"
        ),
        requires=("polars",),
    ),
    # README — hledger/beancount export
    BlockSpec(
        marker="to_hledger(transactions",
        preamble=_TRANSACTIONS_PREAMBLE,
    ),
    # README — Bulk directory scanner
    BlockSpec(
        marker='scan_and_ingest("statements/2026/"',
        preamble="Path('statements/2026').mkdir(parents=True)\n",
    ),
    # README — Account mapping
    BlockSpec(
        marker='AccountMapper.from_json("mapping.json")',
        preamble=(
            _TRANSACTIONS_PREAMBLE
            + "import json\n"
            + "Path('mapping.json').write_text(json.dumps({\n"
            + "    'default': 'Expenses:Uncategorized',\n"
            + "    'rules': [\n"
            + "        {'pattern': 'SALARY', 'account': 'Income:Salary'},\n"
            + "        {'pattern': 'COFFEE', "
            + "'account': 'Expenses:Food:Coffee'},\n"
            + "    ],\n"
            + "}))\n"
        ),
    ),
    # README — Multi-currency verification
    BlockSpec(
        marker="verify_balance_multi_currency(",
        preamble=(
            _TRANSACTIONS_PREAMBLE
            + "opening = Decimal('0.00')\nclosing = Decimal('100.00')\n"
        ),
    ),
    # FAQ — VisionExtractor strip mode (needs a live vision model + PDF)
    BlockSpec(
        marker="VisionExtractor(strip_rows=True",
        mode="imports",
        reason="requires a live vision LLM and a scanned PDF",
    ),
    # docs/index — Quick start
    BlockSpec(
        marker="parser.get_account_balances()",
        files=(("statement.xml", CAMT_FIXTURE),),
    ),
    # docs/index — Automatic format detection
    BlockSpec(
        marker='create_parser("statement.ofx")',
        files=(("statement.ofx", OFX_FIXTURE),),
    ),
    # docs/MAPPING — Transaction.from_record
    BlockSpec(
        marker="Transaction.from_record(",
        preamble=(
            "from bankstatementparser import CamtParser\n"
            f"parser = CamtParser({str(CAMT_FIXTURE)!r})\n"
        ),
    ),
)


def _matching_blocks(spec: BlockSpec) -> list[DocBlock]:
    return [b for b in PYTHON_BLOCKS if spec.marker in b.body]


# ----------------------------------------------------------------------
# Structural guarantees
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "block", PYTHON_BLOCKS, ids=[b.location for b in PYTHON_BLOCKS]
)
def test_python_block_is_valid_syntax(block: DocBlock) -> None:
    ast.parse(block.body, filename=block.location)


def test_every_python_block_is_classified() -> None:
    """Each documented python block maps to exactly one BlockSpec."""
    unmatched = [
        b.location
        for b in PYTHON_BLOCKS
        if not any(spec.marker in b.body for spec in BLOCK_SPECS)
    ]
    assert not unmatched, (
        "Unclassified python blocks in docs (add a BlockSpec so the "
        f"example is executed by the regression suite): {unmatched}"
    )

    for spec in BLOCK_SPECS:
        matches = _matching_blocks(spec)
        assert len(matches) == 1, (
            f"BlockSpec marker {spec.marker!r} must match exactly one "
            f"block, matched {[b.location for b in matches]}"
        )


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------


def _spec_id(spec: BlockSpec) -> str:
    blocks = _matching_blocks(spec)
    return blocks[0].location if blocks else spec.marker[:30]


@pytest.mark.parametrize(
    "spec", BLOCK_SPECS, ids=[_spec_id(s) for s in BLOCK_SPECS]
)
def test_documented_python_block(
    spec: BlockSpec,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocks = _matching_blocks(spec)
    assert len(blocks) == 1
    block = blocks[0]

    missing = [dep for dep in spec.requires if not _has(dep)]
    if missing:
        pytest.skip(f"{block.location} requires {', '.join(missing)}")

    if spec.mode == "imports":
        tree = ast.parse(block.body)
        import_lines = [
            ast.unparse(node)
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        assert import_lines, (
            f"{block.location} is imports-only ({spec.reason}) but has "
            "no imports to verify"
        )
        namespace: dict[str, object] = {}
        exec(
            compile("\n".join(import_lines), block.location, "exec"),
            namespace,
        )
        return

    monkeypatch.chdir(tmp_path)
    for placeholder, fixture in spec.files:
        target = tmp_path / placeholder
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fixture.read_bytes())

    namespace = {"__name__": "bsp_doc_example"}
    if spec.preamble:
        exec(
            compile(
                _COMMON_PREAMBLE + spec.preamble,
                f"{block.location}-preamble",
                "exec",
            ),
            namespace,
        )
    exec(compile(block.body, block.location, "exec"), namespace)
    capsys.readouterr()  # examples are allowed to print


# ----------------------------------------------------------------------
# Documented CLI commands
# ----------------------------------------------------------------------


def _run_cli(*args: str, stdin: str | None = None) -> str:
    env = os.environ.copy()
    env["PATH"] = (
        str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    )
    proc = subprocess.run(
        [sys.executable, "-m", "bankstatementparser.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        input=stdin,
        timeout=180,
        env=env,
    )
    assert proc.returncode == 0, (
        f"CLI {' '.join(args)} exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return proc.stdout


def test_cli_doc_flags_all_exist() -> None:
    """Every --flag in a documented CLI invocation must exist."""
    from bankstatementparser.cli import BankStatementCLI

    parser = BankStatementCLI().setup_arg_parser()
    known = {
        opt for action in parser._actions for opt in action.option_strings
    }

    documented: set[str] = set()
    for block in BASH_BLOCKS:
        for raw_line in block.body.splitlines():
            line = raw_line.strip().rstrip("\\").strip()
            if not (
                line.startswith("bankstatementparser ")
                or "-m bankstatementparser.cli" in line
            ):
                continue
            documented.update(
                token for token in shlex.split(line) if token.startswith("--")
            )

    unknown = documented - known
    assert not unknown, f"Docs reference unknown CLI flags: {unknown}"


def test_cli_doc_camt_display() -> None:
    out = _run_cli("--type", "camt", "--input", str(CAMT_FIXTURE))
    assert "AccountId" in out


def test_cli_doc_camt_export_csv(tmp_path: Path) -> None:
    out_csv = tmp_path / "transactions.csv"
    out = _run_cli(
        "--type",
        "camt",
        "--input",
        str(CAMT_FIXTURE),
        "--output",
        str(out_csv),
    )
    assert "saved to" in out
    assert out_csv.exists()


def test_cli_doc_camt_streaming_show_pii() -> None:
    out = _run_cli(
        "--type",
        "camt",
        "--input",
        str(CAMT_FIXTURE),
        "--streaming",
        "--show-pii",
    )
    assert "WARNING: Displaying unredacted PII data" in out


def test_cli_doc_pain001_export_csv(tmp_path: Path) -> None:
    out_csv = tmp_path / "payments.csv"
    out = _run_cli(
        "--type",
        "pain001",
        "--input",
        str(PAIN001_FIXTURE),
        "--output",
        str(out_csv),
    )
    assert "saved to" in out
    assert out_csv.exists()


def test_cli_doc_ingest_display_and_csv(tmp_path: Path) -> None:
    out = _run_cli("--type", "ingest", "--input", str(CAMT_FIXTURE))
    assert "Source method: deterministic" in out

    ledger = tmp_path / "ledger.csv"
    out = _run_cli(
        "--type",
        "ingest",
        "--input",
        str(CAMT_FIXTURE),
        "--output",
        str(ledger),
    )
    assert "Ingested" in out
    header = ledger.read_text(encoding="utf-8").splitlines()[0]
    assert "transaction_hash" in header
    assert "source_method" in header


def _saved_ingest_result(tmp_path: Path) -> Path:
    from bankstatementparser.hybrid import smart_ingest

    result = smart_ingest(str(CAMT_FIXTURE))
    result_path = tmp_path / "result.json"
    result_path.write_text(result.to_json(), encoding="utf-8")
    return result_path


def test_cli_doc_review_roundtrip(tmp_path: Path) -> None:
    result_path = _saved_ingest_result(tmp_path)
    reviewed = tmp_path / "reviewed.json"
    out = _run_cli(
        "--type",
        "review",
        "--input",
        str(result_path),
        "--output",
        str(reviewed),
        stdin="q\n",
    )
    assert "review" in out.lower()


def test_cli_doc_review_below_threshold(tmp_path: Path) -> None:
    result_path = _saved_ingest_result(tmp_path)
    out = _run_cli(
        "--type",
        "review",
        "--input",
        str(result_path),
        "--review-below",
        "0.8",
        stdin="q\n",
    )
    assert "review" in out.lower()
