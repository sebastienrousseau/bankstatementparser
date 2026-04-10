# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0

"""Automated validation that README, docs, and examples stay in sync
with the actual codebase.

If any of these tests fail, the corresponding markdown file has a
stale claim that a human will trust and act on. Fix the docs, not
the test.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
FAQ = REPO_ROOT / "FAQ.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
SECURITY_TOP = REPO_ROOT / "SECURITY.md"
SECURITY_GH = REPO_ROOT / ".github" / "SECURITY.md"
HYBRID_README = REPO_ROOT / "examples" / "hybrid" / "README.md"
EXAMPLES_README = REPO_ROOT / "examples" / "README.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
MAKEFILE = REPO_ROOT / "Makefile"

SRC_DIR = REPO_ROOT / "bankstatementparser"
TESTS_DIR = REPO_ROOT / "tests"
EXAMPLES_DIR = REPO_ROOT / "examples"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Test counts match reality
# ---------------------------------------------------------------------------

_TEST_COUNT_RE = re.compile(r"(\d+)\s+tests")


def _actual_test_count() -> int:
    """Count test functions across all test files."""
    count = 0
    for py in TESTS_DIR.rglob("*.py"):
        content = py.read_text(encoding="utf-8")
        count += len(re.findall(r"^\s*def test_", content, re.MULTILINE))
    return count


def _claimed_test_count(text: str) -> list[int]:
    """Extract every 'N tests' number from a markdown file."""
    return [int(m.group(1)) for m in _TEST_COUNT_RE.finditer(text)]


class TestReadmeAccuracy:
    """Every factual claim in README.md is correct."""

    readme_text = _read(README)

    def test_test_count_matches_reality(self) -> None:
        actual = _actual_test_count()
        for claimed in _claimed_test_count(self.readme_text):
            assert claimed == actual, (
                f"README claims {claimed} tests but "
                f"actual count is {actual}"
            )

    def test_module_count_matches_reality(self) -> None:
        modules = [
            p
            for p in SRC_DIR.rglob("*.py")
            if "__pycache__" not in str(p)
            and ".mypy_cache" not in str(p)
        ]
        actual = len(modules)
        match = re.search(r"(\d+)\s+modules", self.readme_text)
        assert match is not None, "README should mention module count"
        claimed = int(match.group(1))
        assert claimed == actual, (
            f"README claims {claimed} modules but "
            f"actual count is {actual}"
        )

    def test_example_count_matches_reality(self) -> None:
        deterministic = list(EXAMPLES_DIR.glob("*.py"))
        hybrid_py = list((EXAMPLES_DIR / "hybrid").glob("*.py"))
        hybrid_sh = list((EXAMPLES_DIR / "hybrid").glob("*.sh"))
        hybrid_ps = list((EXAMPLES_DIR / "hybrid").glob("*.ps1"))
        hybrid = hybrid_py + hybrid_sh + hybrid_ps
        total = len(deterministic) + len(hybrid)

        assert f"{total} runnable scripts" in self.readme_text or (
            f"{len(deterministic)} deterministic" in self.readme_text
            and f"{len(hybrid)} hybrid" in self.readme_text
        ), (
            f"README claims don't match actual: "
            f"{len(deterministic)} det + {len(hybrid)} hybrid = {total}"
        )

    def test_python_version_matches_pyproject(self) -> None:
        pyproject = _read(PYPROJECT)
        if ">=3.10" in pyproject:
            assert "3.10" in self.readme_text, (
                "README should mention Python 3.10 minimum"
            )
        if ">=3.9" in pyproject:
            assert "3.9" in self.readme_text

    def test_install_extras_match_pyproject(self) -> None:
        pyproject = _read(PYPROJECT)
        for extra in ["hybrid", "hybrid-plus", "hybrid-vision", "enrichment"]:
            if f'{extra} = [' in pyproject or f"{extra} = [" in pyproject:
                assert extra in self.readme_text, (
                    f"README doesn't mention [{extra}] extra "
                    f"but it exists in pyproject.toml"
                )

    def test_cli_type_choices_documented(self) -> None:
        cli_py = _read(SRC_DIR / "cli.py")
        choices = re.search(
            r'choices=\[([^\]]+)\]', cli_py
        )
        assert choices is not None
        for choice in re.findall(r'"(\w+)"', choices.group(1)):
            assert choice in self.readme_text, (
                f"README doesn't document --type {choice}"
            )

    def test_mermaid_diagram_present(self) -> None:
        assert "```mermaid" in self.readme_text, (
            "README should have a Mermaid diagram"
        )
        assert "smart_ingest" in self.readme_text

    def test_version_badge_matches_pyproject(self) -> None:
        pyproject = _read(PYPROJECT)
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
        assert match is not None
        version = match.group(1)
        assert f"v={version}" in self.readme_text, (
            f"README badge has wrong version (expected v={version})"
        )

    def test_console_script_documented(self) -> None:
        pyproject = _read(PYPROJECT)
        if "bankstatementparser = " in pyproject and "cli:main" in pyproject:
            assert "bankstatementparser --type" in self.readme_text, (
                "README should document the console-script invocation"
            )

    def test_key_features_table_present(self) -> None:
        assert "Key Features" in self.readme_text
        assert "Hybrid PDF pipeline" in self.readme_text
        assert "Golden Rule" in self.readme_text
        assert "Idempotent dedup" in self.readme_text


# ---------------------------------------------------------------------------
# 2. FAQ accuracy
# ---------------------------------------------------------------------------


class TestFaqAccuracy:
    """Every factual claim in FAQ.md is correct."""

    faq_text = _read(FAQ)

    def test_test_count_matches_reality(self) -> None:
        actual = _actual_test_count()
        for claimed in _claimed_test_count(self.faq_text):
            assert claimed == actual, (
                f"FAQ claims {claimed} tests but actual is {actual}"
            )

    def test_hybrid_api_references_exist(self) -> None:
        # Every API function mentioned in the FAQ should be importable
        mentioned = [
            "smart_ingest",
            "verify_balance",
            "VisionExtractor",
        ]
        from bankstatementparser import hybrid

        for name in mentioned:
            if name in self.faq_text:
                assert hasattr(hybrid, name), (
                    f"FAQ references {name} but it's not exported "
                    f"from bankstatementparser.hybrid"
                )

    def test_no_stale_442_467_counts(self) -> None:
        for stale in ["442 tests", "467 tests", "484 tests"]:
            assert stale not in self.faq_text, (
                f"FAQ has stale count: {stale}"
            )


# ---------------------------------------------------------------------------
# 3. CHANGELOG accuracy
# ---------------------------------------------------------------------------


class TestChangelogAccuracy:
    """CHANGELOG.md references correct versions and issues."""

    changelog_text = _read(CHANGELOG)

    def test_current_version_has_entry(self) -> None:
        pyproject = _read(PYPROJECT)
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
        assert match is not None
        version = match.group(1)
        assert f"[{version}]" in self.changelog_text, (
            f"CHANGELOG has no entry for current version {version}"
        )

    def test_v006_closes_all_milestone_issues(self) -> None:
        if "[0.0.6]" not in self.changelog_text:
            pytest.skip("v0.0.6 entry not yet in CHANGELOG")
        v006_section = self.changelog_text.split("[0.0.6]")[1]
        v006_section = v006_section.split("\n## [")[0]
        for issue_num in [44, 45, 46, 47]:
            assert f"#{issue_num}" in v006_section, (
                f"v0.0.6 CHANGELOG doesn't reference issue #{issue_num}"
            )

    def test_no_stale_test_counts_in_current_version(self) -> None:
        actual = _actual_test_count()
        # The CHANGELOG for the CURRENT version should not have stale counts
        pyproject = _read(PYPROJECT)
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
        version = match.group(1) if match else "0.0.0"
        if f"[{version}]" not in self.changelog_text:
            pytest.skip(f"no {version} entry")
        section = self.changelog_text.split(f"[{version}]")[1]
        section = section.split("\n## [")[0]
        for stale in _claimed_test_count(section):
            if stale != actual:
                pytest.fail(
                    f"CHANGELOG v{version} claims {stale} tests "
                    f"but actual is {actual}"
                )


# ---------------------------------------------------------------------------
# 4. CONTRIBUTING.md accuracy
# ---------------------------------------------------------------------------


class TestContributingAccuracy:
    """CONTRIBUTING.md commands actually work."""

    contributing_text = _read(CONTRIBUTING)

    def test_make_verify_documented_and_exists(self) -> None:
        if "make verify" in self.contributing_text:
            makefile = _read(MAKEFILE)
            assert "verify:" in makefile, (
                "CONTRIBUTING.md documents `make verify` but "
                "Makefile has no verify target"
            )

    def test_install_extras_documented(self) -> None:
        pyproject = _read(PYPROJECT)
        if "hybrid-vision" in pyproject:
            assert (
                "hybrid" in self.contributing_text
            ), "CONTRIBUTING should mention hybrid extras for contributors"

    def test_signed_commits_section_present(self) -> None:
        assert "Signed Commits" in self.contributing_text or (
            "signed" in self.contributing_text.lower()
        )


# ---------------------------------------------------------------------------
# 5. SECURITY.md consistency
# ---------------------------------------------------------------------------


class TestSecurityDocs:
    """Top-level and .github/ SECURITY.md files are consistent."""

    def test_both_security_files_exist(self) -> None:
        assert SECURITY_TOP.exists(), "Top-level SECURITY.md missing"
        assert SECURITY_GH.exists(), ".github/SECURITY.md missing"

    def test_top_level_is_redirect(self) -> None:
        text = _read(SECURITY_TOP)
        assert ".github/SECURITY.md" in text, (
            "Top-level SECURITY.md should reference .github/SECURITY.md"
        )

    def test_github_security_has_current_version(self) -> None:
        text = _read(SECURITY_GH)
        pyproject = _read(PYPROJECT)
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
        if match:
            version = match.group(1)
            assert version in text, (
                f".github/SECURITY.md doesn't list current "
                f"version {version} in Supported Versions"
            )


# ---------------------------------------------------------------------------
# 6. Examples actually exist and are importable
# ---------------------------------------------------------------------------


class TestExamplesExist:
    """Every example script mentioned in README/examples/README exists."""

    readme_text = _read(README)
    examples_readme_text = _read(EXAMPLES_README)

    def _extract_script_paths(self, text: str) -> list[str]:
        """Pull script paths from markdown table rows."""
        # Matches patterns like `script.py` or `hybrid/script.py`
        return re.findall(
            r"`((?:hybrid/)?[\w]+\.(?:py|sh|ps1))`", text
        )

    def test_all_readme_example_scripts_exist(self) -> None:
        scripts = self._extract_script_paths(self.readme_text)
        for script in scripts:
            path = EXAMPLES_DIR / script
            assert path.exists(), (
                f"README references examples/{script} but file "
                f"doesn't exist"
            )

    def test_all_examples_readme_scripts_exist(self) -> None:
        scripts = self._extract_script_paths(self.examples_readme_text)
        for script in scripts:
            path = EXAMPLES_DIR / script
            assert path.exists(), (
                f"examples/README.md references {script} but file "
                f"doesn't exist"
            )

    def test_example_python_scripts_compile(self) -> None:
        """Every .py example passes py_compile (no syntax errors)."""
        for py in sorted(EXAMPLES_DIR.rglob("*.py")):
            if "__pycache__" in str(py):
                continue
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(py)],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"Example {py.relative_to(REPO_ROOT)} has syntax "
                f"errors: {result.stderr}"
            )


# ---------------------------------------------------------------------------
# 7. Public API surface documented
# ---------------------------------------------------------------------------


class TestApiSurface:
    """Key public symbols are mentioned in documentation."""

    readme_text = _read(README)

    def test_core_exports_mentioned(self) -> None:
        """Critical public API symbols should appear somewhere in README."""
        must_mention = [
            "CamtParser",
            "Pain001Parser",
            "detect_statement_format",
            "create_parser",
            "Transaction",
            "Deduplicator",
            "smart_ingest",
        ]
        for sym in must_mention:
            assert sym in self.readme_text, (
                f"README doesn't mention public API symbol '{sym}'"
            )

    def test_boundingbox_in_docs(self) -> None:
        """BoundingBox is a v0.0.6 addition — should be documented."""
        combined = self.readme_text + _read(CHANGELOG)
        assert "BoundingBox" in combined, (
            "BoundingBox should be mentioned in README or CHANGELOG"
        )

    def test_enrichment_in_docs(self) -> None:
        """Enrichment module is a v0.0.6 addition — should be documented."""
        combined = self.readme_text + _read(CHANGELOG)
        assert "enrichment" in combined.lower(), (
            "Enrichment module should be mentioned in README or CHANGELOG"
        )

    def test_review_mode_in_docs(self) -> None:
        """Review mode is a v0.0.6 addition — should be documented."""
        combined = self.readme_text + _read(CHANGELOG)
        assert "review" in combined.lower(), (
            "Review mode should be mentioned in README or CHANGELOG"
        )


# ---------------------------------------------------------------------------
# 8. Cross-file consistency
# ---------------------------------------------------------------------------


class TestCrossFileConsistency:
    """Numbers and claims are consistent across all markdown files."""

    def test_all_docs_agree_on_test_count(self) -> None:
        actual = _actual_test_count()
        files = {
            "README.md": README,
            "FAQ.md": FAQ,
        }
        for name, path in files.items():
            for claimed in _claimed_test_count(_read(path)):
                assert claimed == actual, (
                    f"{name} claims {claimed} tests but actual is {actual}"
                )

    def test_pyproject_version_consistent_everywhere(self) -> None:
        pyproject = _read(PYPROJECT)
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
        assert match is not None
        version = match.group(1)

        # Check setup.cfg
        setup_cfg = REPO_ROOT / "setup.cfg"
        if setup_cfg.exists():
            cfg_text = _read(setup_cfg)
            cfg_match = re.search(r"version\s*=\s*(\S+)", cfg_text)
            if cfg_match:
                assert cfg_match.group(1) == version, (
                    f"setup.cfg version {cfg_match.group(1)} "
                    f"!= pyproject.toml {version}"
                )

    def test_no_references_to_dropped_python_39(self) -> None:
        """After v0.0.6, Python 3.9 should not appear as 'supported'."""
        pyproject = _read(PYPROJECT)
        if ">=3.10" in pyproject:
            # v0.0.6+ — 3.9 should not be in any CI matrix
            workflow = REPO_ROOT / ".github" / "workflows" / "quality-gates.yml"
            if workflow.exists():
                wf_text = _read(workflow)
                assert '"3.9"' not in wf_text, (
                    "CI matrix still includes Python 3.9 but "
                    "pyproject.toml requires >=3.10"
                )
