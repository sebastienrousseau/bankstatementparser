# SPDX-FileCopyrightText: 2026 Sebastien Rousseau <sebastian.rousseau@gmail.com>
# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Suite conformance: the invariants every repository in the family holds.

This file is generated from one canonical copy and vendored into each
repository, so all 32 assert the same things. `test_this_file_is_the_canonical
_copy` fails if a local edit drifts from that copy — change the canonical one
and re-run the rollout, never this.

Each assertion here exists because the suite has already shipped the failure it
describes:

* `iso20022-mcp` 0.0.7 published with `__version__` reading 0.0.6, so a client
  asking the server what it was talking to got the wrong answer.
* `iso20022-mcp[all]` 0.0.6 was unsatisfiable — a floor raised past a sibling's
  cap. Nothing in that repository failed; only the user's `pip install` did.
* `acmt001-mcp` 0.0.7 was bumped in the tree, never tagged, and never
  published, so an advisory fix sat unreleased for ten days.
* `acmt001-lsp` sat at 73% coverage because it had no gate to notice.
* `bankstatementparser` had 43 test files and no CI workflow to run them.

None of these were visible from inside the repository that carried them. That
is the point of a conformance file: it makes the invisible failures loud, in
the pull request, before they reach anybody.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):  # pragma: no cover - version dependent
    import tomllib
else:  # pragma: no cover - version dependent
    # `tomllib` is stdlib only from 3.11, and the suite floor is 3.10.
    import tomli as tomllib

# Normally the repository this file sits in. The environment override exists
# for the rollout tool, which checks every repository in the suite from one
# place; nothing in CI sets it.
ROOT = Path(
    os.environ.get("SUITE_CONFORMANCE_ROOT")
    or Path(__file__).resolve().parent.parent
).resolve()
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
HEADING = re.compile(r"^## \[?(\d+\.\d+\.\d+)\]?", re.MULTILINE)

#: The floor every repository in the suite gates at. Raised deliberately and
#: together; a single repository lowering it is the drift this catches.
MINIMUM_COVERAGE = 98

#: Files every repository ships. A user landing on any one of these
#: repositories should find the same things in the same places.
REQUIRED_FILES = (
    "README.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "LICENSE",
)

#: Directories every repository ships. `benches/` is here because a
#: performance regression is the one kind that passes every test.
REQUIRED_DIRS = ("docs", "examples", "benches", "tests")


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def _poetry() -> dict:
    return dict(_pyproject().get("tool", {}).get("poetry", {}))


def _is_poetry() -> bool:
    """26 of the 32 repositories build with poetry-core, six with hatchling.

    The two put the same facts in different places, so everything below reads
    through these helpers rather than assuming a layout. Unifying the backends
    would be a larger change than this file is entitled to make.
    """
    backend = _pyproject().get("build-system", {}).get("build-backend", "")
    return "poetry" in backend


def _declared_dependencies() -> dict[str, object]:
    """Runtime dependencies, keyed by name, in whichever layout is in use."""
    if _is_poetry():
        deps = dict(_poetry().get("dependencies", {}))
        deps.pop("python", None)
        return deps
    from packaging.requirements import Requirement

    out: dict[str, object] = {}
    for raw in _pyproject().get("project", {}).get("dependencies", []):
        requirement = Requirement(raw)
        out[requirement.name] = str(requirement.specifier)
    return out


def _dev_tools() -> set[str]:
    """Names of the declared development tools, in whichever layout."""
    if _is_poetry():
        groups = _poetry().get("group", {})
        names: set[str] = set()
        for group in groups.values():
            names |= set(group.get("dependencies", {}))
        return names
    from packaging.requirements import Requirement

    optional = _pyproject().get("project", {}).get("optional-dependencies", {})
    names = set()
    for entries in optional.values():
        for raw in entries:
            names.add(Requirement(raw).name)
    for group in _pyproject().get("dependency-groups", {}).values():
        for raw in group:
            if isinstance(raw, str):
                names.add(Requirement(raw).name)
    return names


def _dev_spec(tool: str) -> str:
    """The version constraint declared for a development tool."""
    if _is_poetry():
        for group in _poetry().get("group", {}).values():
            if tool in group.get("dependencies", {}):
                raw = group["dependencies"][tool]
                spec = raw if isinstance(raw, str) else raw.get("version", "")
                return ",".join(str(spec).split())
        return ""
    from packaging.requirements import Requirement

    optional = _pyproject().get("project", {}).get("optional-dependencies", {})
    for entries in optional.values():
        for raw in entries:
            requirement = Requirement(raw)
            if requirement.name == tool:
                return str(requirement.specifier)
    for group in _pyproject().get("dependency-groups", {}).values():
        for raw in group:
            if isinstance(raw, str) and Requirement(raw).name == tool:
                return str(Requirement(raw).specifier)
    return ""


def _package_dir() -> Path:
    """The one importable package directory in the repository root."""
    candidates = [
        p
        for p in ROOT.iterdir()
        if p.is_dir()
        and (p / "__init__.py").exists()
        and not p.name.startswith((".", "test"))
        and p.name not in {"docs", "examples", "benches"}
    ]
    assert len(candidates) == 1, (
        f"expected exactly one importable package directory, found "
        f"{[p.name for p in candidates]}"
    )
    return candidates[0]


def _declared_version() -> str:
    poetry_version = _poetry().get("version")
    project_version = _pyproject().get("project", {}).get("version")
    version = poetry_version or project_version
    assert version, "neither [tool.poetry] nor [project] declares a version"
    return str(version)


def _restated_versions() -> dict[str, str]:
    """Every place in the tree that repeats the version number."""
    found = {"pyproject.toml": _declared_version()}
    package = _package_dir()
    for name in ("__init__.py", "constants.py", "_version.py"):
        path = package / name
        if not path.exists():
            continue
        for pattern in (
            r"__version__\s*=\s*[\"']([^\"']+)",
            r"^VERSION\s*=\s*[\"']([^\"']+)",
        ):
            match = re.search(
                pattern, path.read_text(encoding="utf-8"), re.MULTILINE
            )
            if match:
                found[f"{package.name}/{name}"] = match.group(1)
                break
    return found


def _changelog_versions() -> list[str]:
    return HEADING.findall(CHANGELOG.read_text(encoding="utf-8"))


def _addopts() -> str:
    """pytest accepts ``addopts`` as a list or a single string.

    Both forms are in use across the suite. Joining a *string* with
    ``" ".join`` spaces out its characters, so a gate configured the string
    way reads as absent — which is exactly the false positive this helper
    exists to stop.
    """
    ini = _pyproject().get("tool", {}).get("pytest", {}).get("ini_options", {})
    addopts = ini.get("addopts", [])
    if isinstance(addopts, str):
        return addopts
    return " ".join(addopts)


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------
def test_the_version_is_semver() -> None:
    version = _declared_version()
    assert SEMVER.match(version), f"version is {version!r}, which is not X.Y.Z"


def test_every_restatement_of_the_version_agrees() -> None:
    """`iso20022-mcp` 0.0.7 shipped with `__version__` reading 0.0.6."""
    found = _restated_versions()
    assert len(set(found.values())) == 1, (
        "the version is restated in several places and they disagree: "
        + ", ".join(f"{where}={what}" for where, what in sorted(found.items()))
    )


def test_the_package_restates_the_version_at_least_once() -> None:
    """A package with no `__version__` cannot report itself to a client."""
    found = _restated_versions()
    assert len(found) > 1, (
        f"{_package_dir().name} declares no __version__; a client asking this "
        f"package what it is has nothing to read"
    )


def test_the_changelog_documents_the_current_version() -> None:
    versions = _changelog_versions()
    assert versions, "CHANGELOG.md has no '## [X.Y.Z]' headings"
    assert _declared_version() in versions, (
        f"CHANGELOG.md has no entry for {_declared_version()}; newest "
        f"documented is {versions[0]} — a release was cut without one"
    )


def test_the_newest_changelog_entry_is_the_current_version() -> None:
    versions = _changelog_versions()
    assert versions[0] == _declared_version(), (
        f"newest CHANGELOG entry is {versions[0]} but the package is "
        f"{_declared_version()}"
    )


def test_changelog_entries_are_ordered_newest_first() -> None:
    versions = _changelog_versions()
    keyed = [tuple(int(part) for part in v.split(".")) for v in versions]
    assert keyed == sorted(keyed, reverse=True), (
        f"CHANGELOG.md entries are out of order: {versions}"
    )


def test_the_changelog_documents_each_version_once() -> None:
    versions = _changelog_versions()
    duplicates = {v for v in versions if versions.count(v) > 1}
    assert not duplicates, (
        f"CHANGELOG.md documents {duplicates} more than once"
    )


# ---------------------------------------------------------------------------
# The coverage gate
# ---------------------------------------------------------------------------
def test_a_coverage_gate_is_configured_and_meets_the_suite_floor() -> None:
    """The floor must hold for a plain local ``pytest``, not only in CI.

    Two things are needed, and most of the suite has only the second:

    * ``--cov`` in ``addopts``, so coverage runs at all. Without it a local
      ``pytest`` measures nothing, the developer sees green, and CI tells
      them otherwise.
    * A floor. Either ``--cov-fail-under`` in ``addopts`` or ``fail_under``
      under ``[tool.coverage.report]`` — pytest-cov honours the latter, so
      the number belongs there and nowhere else. Stating it twice is how
      two values meant to be equal drift apart.

    Most of the suite does enforce a floor from the CI workflow, so this is
    not a hole through which coverage silently falls. `acmt001-lsp` is the
    case that had neither, and sat at 73%.
    """
    addopts = _addopts()
    assert "--cov" in addopts, (
        "no --cov in [tool.pytest.ini_options] addopts, so a local pytest "
        "measures no coverage at all and only CI ever checks"
    )

    inline = re.search(r"--cov-fail-under=([\d.]+)", addopts)
    configured = (
        _pyproject()
        .get("tool", {})
        .get("coverage", {})
        .get("report", {})
        .get("fail_under")
    )
    assert inline or configured is not None, (
        "coverage runs but has no floor: neither --cov-fail-under in "
        "addopts nor fail_under under [tool.coverage.report]"
    )
    gate = float(inline.group(1)) if inline else float(configured)
    assert gate >= MINIMUM_COVERAGE, (
        f"the coverage gate is {gate}%, below the suite floor of "
        f"{MINIMUM_COVERAGE}%"
    )


def test_the_coverage_floor_is_stated_once() -> None:
    """Two copies of the same number is how they stop being the same."""
    inline = re.search(r"--cov-fail-under=([\d.]+)", _addopts())
    configured = (
        _pyproject()
        .get("tool", {})
        .get("coverage", {})
        .get("report", {})
        .get("fail_under")
    )
    if inline and configured is not None:
        assert float(inline.group(1)) == float(configured), (
            f"addopts says --cov-fail-under={inline.group(1)} but "
            f"[tool.coverage.report] says fail_under={configured}"
        )


def test_coverage_measures_branches_not_just_lines() -> None:
    """Line coverage calls a half-tested `if` fully covered."""
    addopts = _addopts()
    branch = (
        _pyproject()
        .get("tool", {})
        .get("coverage", {})
        .get("run", {})
        .get("branch")
    )
    assert "--cov-branch" in addopts or branch is True, (
        "branch coverage is off, so a partly-tested conditional counts as "
        "covered"
    )


# ---------------------------------------------------------------------------
# What every repository ships
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", REQUIRED_FILES)
def test_the_repository_ships_the_expected_file(name: str) -> None:
    assert (ROOT / name).is_file(), (
        f"{name} is missing; every repository in the suite carries one so a "
        f"reader finds the same things in the same places"
    )


@pytest.mark.parametrize("name", REQUIRED_DIRS)
def test_the_repository_ships_the_expected_directory(name: str) -> None:
    path = ROOT / name
    assert path.is_dir(), f"{name}/ is missing"
    assert any(path.rglob("*")), f"{name}/ exists but is empty"


def test_benches_are_runnable_python() -> None:
    """A benchmark nobody can run is documentation with a misleading name."""
    scripts = sorted((ROOT / "benches").rglob("*.py"))
    assert scripts, "benches/ contains no Python"
    for script in scripts:
        source = script.read_text(encoding="utf-8")
        compile(source, str(script), "exec")


def test_examples_are_runnable_python() -> None:
    scripts = sorted((ROOT / "examples").rglob("*.py"))
    assert scripts, "examples/ contains no Python"
    for script in scripts:
        compile(script.read_text(encoding="utf-8"), str(script), "exec")


# ---------------------------------------------------------------------------
# Toolchain
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tool", ["ruff", "mypy", "pytest", "pytest-cov"])
def test_the_toolchain_is_declared(tool: str) -> None:
    """CI installing a tool the tree does not declare is how versions drift.

    `black` is deliberately not in this list. The suite formats with two
    tools — black in most repositories, `ruff format` in the rest — and
    requiring one would force a formatter change on repositories that chose
    the other. `test_a_formatter_is_configured` checks that *some* formatter
    is set up; this checks the tools every repository genuinely shares.
    """
    assert tool in _dev_tools(), (
        f"{tool} is not declared as a development dependency, so CI installs "
        f"a version the tree says nothing about"
    )


def test_a_formatter_runs_somewhere() -> None:
    """Either formatter is fine; none is not.

    Configuration in `pyproject.toml` is one signal, but `ruff format` with
    its defaults needs no section and is a perfectly good choice — so the
    workflows count too. What this rules out is a repository where nothing
    formats and diffs carry reformatting noise that hides the change under
    review.
    """
    tool = _pyproject().get("tool", {})
    configured = (
        "black" in tool
        or "black" in _dev_tools()
        or "format" in tool.get("ruff", {})
    )
    workflows = ROOT / ".github" / "workflows"
    text = (
        "\n".join(
            p.read_text(encoding="utf-8") for p in workflows.glob("*.yml")
        )
        if workflows.is_dir()
        else ""
    )
    enforced = "ruff format" in text or "black --check" in text
    assert configured or enforced, (
        "no formatter is configured in pyproject.toml and none runs in CI"
    )


def test_black_is_above_the_advisory_floor() -> None:
    """Only applies where black is used. `acmt001-lsp` pinned `^24.0.0`.

    Versions in >=24.3.0, <26.3.1 allow arbitrary file writes through an
    unsanitised cache filename. A caret constraint below 26 does not merely
    resolve to a vulnerable version — it makes the fix unreachable, so the
    constraint itself is the defect.
    """
    from packaging.requirements import Requirement
    from packaging.version import Version

    spec = _dev_spec("black")
    if not spec:
        pytest.skip("this repository does not use black")
    if spec.startswith("^"):
        major = int(spec[1:].split(".")[0])
        assert major >= 26, (
            f"black {spec} cannot reach 26.3.1, the release that patches the "
            f"cache-filename advisory"
        )
        return
    assert Requirement(f"black{spec}").specifier.contains(Version("26.3.1")), (
        f"black{spec} excludes 26.3.1, the release that patches the "
        f"cache-filename advisory"
    )


def test_no_sibling_dependency_is_capped_inside_its_own_major() -> None:
    """`<0.0.61` on a sibling is what made `iso20022-mcp[all]` fail.

    A major cap (`<1` on a 0.x package) is conventional and is not what this
    catches — every repository in the suite carries those deliberately. What
    broke was a cap *inside* the series, which excludes the sibling's own
    later releases. Nothing failed in the repository that added it; only the
    user's `pip install` did.
    """
    from packaging.requirements import Requirement
    from packaging.version import Version

    prefixes = (
        "pain001",
        "pacs008",
        "camt053",
        "acmt001",
        "bankstatementparser",
        "iso20022",
        "structured-address-fix",
        "camt-exceptions",
    )
    capped = []
    for name, raw in _declared_dependencies().items():
        if not name.startswith(prefixes):
            continue
        spec = raw if isinstance(raw, str) else raw.get("version", "")  # type: ignore[union-attr]
        spec = ",".join(str(spec).split())
        if not spec or spec.startswith("^"):
            continue
        # The whole 0.x series must stay reachable. `<1` admits 0.999.999 and
        # passes; `<0.0.61` does not and fails, which is exactly the
        # distinction that matters.
        if not Requirement(f"{name}{spec}").specifier.contains(
            Version("0.999.999")
        ):
            capped.append(f"{name}{spec}")
    assert not capped, (
        "these sibling constraints are capped inside their own release "
        "series, which is how iso20022-mcp[all] became "
        f"unsatisfiable: {capped}"
    )


# ---------------------------------------------------------------------------
# CI
# ---------------------------------------------------------------------------
def test_a_ci_workflow_runs_the_tests() -> None:
    """`bankstatementparser` had 43 test files and no workflow to run them."""
    workflows = ROOT / ".github" / "workflows"
    assert workflows.is_dir(), ".github/workflows/ is missing"
    text = "\n".join(
        p.read_text(encoding="utf-8") for p in workflows.glob("*.yml")
    )
    assert "pytest" in text, (
        "no workflow runs pytest; the tests in this repository are never "
        "executed by CI"
    )


def test_ci_runs_on_pull_requests() -> None:
    """A gate that only runs after merge is not a gate."""
    workflows = ROOT / ".github" / "workflows"
    text = "\n".join(
        p.read_text(encoding="utf-8") for p in workflows.glob("*.yml")
    )
    assert "pull_request" in text, (
        "no workflow triggers on pull_request, so nothing checks a change "
        "before it lands on main"
    )


def test_a_scheduled_check_compares_the_tree_to_what_is_published() -> None:
    """Catch the release that was bumped in the tree and never shipped.

    This has now happened three times in the suite -- `acmt001-mcp` 0.0.7,
    `ap2-iso20022` 0.0.3, `camt-exceptions` 0.0.16 -- and each time the
    version carried a `cryptography` advisory floor that therefore reached
    nobody. Nothing fails when it happens: the tree is consistent, the
    tests pass, the changelog is written. Only PyPI disagrees, and only if
    somebody goes and looks.

    A test inside the repository cannot look, because at commit time the
    tag legitimately does not exist yet. A shallow CI checkout cannot look
    either -- `actions/checkout` fetches no tags by default, so a
    git-based assertion would fail spuriously rather than catch anything.

    What does work is a *scheduled* job that compares the tree against the
    index, which is what `camt053` already does in
    `scripts/check_suite_consistency.py`. This asserts the mechanism
    exists rather than trying to replace it.
    """
    workflows = ROOT / ".github" / "workflows"
    assert workflows.is_dir(), ".github/workflows/ is missing"
    for path in workflows.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        # Matched on the bare word rather than the hostname. It catches
        # strictly more -- "pypi.org", "PyPI", a pypi-json helper -- and
        # it stops CodeQL reading a containment test against a
        # dotted host as an incomplete URL sanitisation, which it did:
        # py/incomplete-url-substring-sanitization, high severity, on a
        # line that never validates a URL in the first place.
        lowered = text.lower()
        if "schedule:" in text and (
            "pypi" in lowered or "consistency" in lowered
        ):
            return
    raise AssertionError(
        "no scheduled workflow compares this package's version against "
        "what is published. A version bumped in the tree and never "
        "released breaks nothing and is invisible until somebody looks; "
        "see camt053's suite-consistency workflow for the pattern"
    )


def test_a_release_is_published_by_a_workflow_not_by_hand() -> None:
    """`pain001` had none: 96 tests, and releases cut by hand.

    What this is really asserting is that publishing is *automated*, so
    the tree and the index cannot drift apart through somebody forgetting
    a step. There is more than one honest way to wire that up: a tag push
    can trigger the upload directly, or the tag can create a GitHub
    release which triggers it. `bankstatementparser` uses the second and
    was failing this check purely on wording -- the earlier version
    matched the literal `tags:` and nothing else, which made a correctly
    automated repository look manual.
    """
    workflows = ROOT / ".github" / "workflows"
    texts = [p.read_text(encoding="utf-8") for p in workflows.glob("*.yml")]
    triggered_by_tag_or_release = [
        t for t in texts if "tags:" in t or "release:" in t
    ]
    assert any(
        "pypi" in t.lower() for t in triggered_by_tag_or_release
    ), (
        "no workflow publishes to PyPI on a tag or a published release; "
        "releases are manual and so the tree and the index can disagree"
    )


# ---------------------------------------------------------------------------
# This file
# ---------------------------------------------------------------------------
CANONICAL_SHA256 = "950a6ea78e17a122ec688f30b79c95fdd29a23e0ed78bb8c46eeb623d6e6e1de"  # fmt: skip # noqa: E501


def test_this_file_is_the_canonical_copy() -> None:
    """Vendored, so it can drift. This is what stops it.

    Edit the canonical copy and re-run the rollout. A repository that needs an
    exemption should say so in its own test file, not by quietly weakening the
    shared one.
    """
    if CANONICAL_SHA256 == "PLACEHOLDER":  # pragma: no cover - pre-rollout
        pytest.skip("canonical hash not yet stamped")
    # Every occurrence of the constant is blanked, not just the assignment:
    # the name also appears in the line below, and normalising one but not
    # the other makes the round-trip asymmetric and the check always fail.
    source = Path(__file__).read_text(encoding="utf-8")
    body = re.sub(
        r"^CANONICAL_SHA256 = .*$",
        "CANONICAL_SHA256 = BLANK",
        source,
        flags=re.MULTILINE,
    )
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert digest == CANONICAL_SHA256, (
        "this file has been edited away from the canonical suite copy; "
        "change the canonical one and re-run the rollout"
    )


def test_the_python_floor_is_at_least_the_suite_floor() -> None:
    """A package supporting *less* than the suite cannot ship with it.

    The floor is 3.10, which 30 of the 32 repositories declare. This
    asserts nothing below that, rather than exactly that: a *higher* floor
    is a compatibility decision somebody made, not a conformance failure,
    and this test is not the place to overrule it.

    One ecosystem does sit higher. `structured-address-fix` and
    `structured-address-fix-mcp` both require >=3.12 — consistently, so it
    reads as deliberate. The consequence is worth knowing rather than
    silently passing: **those two cannot be installed alongside the rest
    of the suite on 3.10 or 3.11.** Whether that is intended is a decision
    for the maintainer; what would be a defect is a floor *below* 3.10, or
    two members of one ecosystem disagreeing.
    """
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    raw = str(
        _poetry().get("dependencies", {}).get("python")
        or _pyproject().get("project", {}).get("requires-python", "")
    )
    assert raw, "no Python requirement declared"

    # Poetry's caret form is not PEP 440. `^3.10` means >=3.10,<4.
    spec = raw
    if spec.startswith("^"):
        spec = f">={spec[1:]},<{int(spec[1:].split('.')[0]) + 1}"
    spec = ",".join(spec.split())

    specifier = SpecifierSet(spec)
    assert not specifier.contains(Version("3.9")), (
        f"python {raw} admits 3.9, below the suite floor of 3.10"
    )


def test_the_running_interpreter_is_supported() -> None:
    """Guards against a CI matrix drifting below what the tree claims."""
    assert sys.version_info >= (3, 10)
