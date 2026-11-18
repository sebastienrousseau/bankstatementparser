# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
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
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for ``scripts/release_notes.py``, the release body composer."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = "owner/project"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "release_notes", ROOT / "scripts" / "release_notes.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rn = _load()

GOOD = (
    "* **First**: one sentence that\n"
    "  wraps onto a second line.\n"
    "\n"
    "* **Second**: another sentence.\n"
)


def _pull(
    number: int, login: str = "dev", kind: str = "User"
) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"fix: change {number}",
        "user": {"login": login, "type": kind},
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "merged_at": "2026-11-18T00:00:00Z",
        "base": {"ref": "main"},
    }


def _commit(sha: str, login: str | None = "dev") -> dict[str, Any]:
    return {
        "sha": sha,
        "html_url": f"https://github.com/{REPO}/commit/{sha}",
        "author": {"login": login} if login else None,
        "commit": {
            "message": f"chore: {sha}\n\nbody",
            "author": {"name": "Dev Name"},
        },
    }


def _sections(**overrides: list[str]) -> dict[str, list[str]]:
    sections = {
        "highlights": ["* **A**: a.", "* **B**: b."],
        "changes": ["* fix: x by @dev in https://example.test/1"],
        "contributors": [],
        "checksums": ["0" * 64 + "  pkg.whl"],
    }
    sections.update(overrides)
    return sections


def test_highlights_join_wrapped_lines(tmp_path: Path) -> None:
    path = tmp_path / "v0.0.2.md"
    path.write_text(GOOD, encoding="utf-8")
    bullets = rn.load_highlights(path)
    assert bullets == [
        "* **First**: one sentence that wraps onto a second line.",
        "* **Second**: another sentence.",
    ]
    rn.validate_highlights(bullets, path)


def test_missing_highlights_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(rn.NotesError, match="missing"):
        rn.load_highlights(tmp_path / "absent.md")


@pytest.mark.parametrize(
    ("bullets", "message"),
    [
        (["* **Only**: one."], "found 1"),
        ([f"* **N{i}**: text." for i in range(5)], "found 5"),
        (["* **A**: a.", "- plain bullet"], "not a"),
        (["* **A**: a.", "* **B**:"], "not a"),
        (["* **A**: a.", "* **B**: x — y."], "em dash"),
    ],
)
def test_bad_highlights_are_rejected(bullets: list[str], message: str) -> None:
    with pytest.raises(rn.NotesError, match=message):
        rn.validate_highlights(bullets, Path("h.md"))


def test_previous_tag_is_the_highest_lower_version() -> None:
    tags = ["v0.0.9", "v0.0.10", "v0.0.11", "latest", "v0.0.2"]
    assert rn.previous_tag("v0.0.11", tags) == "v0.0.10"
    assert rn.previous_tag("v0.0.2", tags) is None
    with pytest.raises(rn.NotesError, match="not a vX"):
        rn.previous_tag("release", tags)


def test_changes_prefer_pull_requests() -> None:
    lines = rn.change_lines([_pull(7), _pull(3)], [_commit("a")])
    assert lines == [
        f"* fix: change 3 by @dev in https://github.com/{REPO}/pull/3",
        f"* fix: change 7 by @dev in https://github.com/{REPO}/pull/7",
    ]


def test_changes_fall_back_to_commits() -> None:
    lines = rn.change_lines([], [_commit("abc"), _commit("def", login=None)])
    assert lines == [
        f"* chore: abc by @dev in https://github.com/{REPO}/commit/abc",
        f"* chore: def by @Dev Name in https://github.com/{REPO}/commit/def",
    ]


def test_checksums_cover_every_file(tmp_path: Path) -> None:
    (tmp_path / "b.tar.gz").write_bytes(b"sdist")
    (tmp_path / "A.whl").write_bytes(b"wheel")
    (tmp_path / "subdir").mkdir()
    assert rn.checksum_lines(tmp_path) == [
        f"{hashlib.sha256(b'wheel').hexdigest()}  A.whl",
        f"{hashlib.sha256(b'sdist').hexdigest()}  b.tar.gz",
    ]


def test_compose_has_the_required_sections_in_order() -> None:
    body = rn.compose(REPO, "v0.0.2", "v0.0.1", _sections())
    headings = [
        line
        for line in body.splitlines()
        if line.startswith(("## ", "**Full"))
    ]
    assert headings == [
        "## Highlights ⭐️",
        "## What's Changed",
        "## Checksums",
        f"**Full Changelog**: https://github.com/{REPO}/compare/v0.0.1...v0.0.2",
    ]
    assert (
        "SHA-256 of every asset attached to this release:\n\n```text\n" in body
    )


def test_compose_lists_new_contributors_and_first_tag() -> None:
    sections = _sections(
        contributors=rn.contributor_lines({"new": _pull(4, "new")})
    )
    body = rn.compose(REPO, "v0.0.1", None, sections)
    assert (
        "## New Contributors\n\n* @new made their first contribution in"
        in body
    )
    assert body.index("## New Contributors") < body.index("## Checksums")
    assert body.endswith(f"https://github.com/{REPO}/commits/v0.0.1\n")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"changes": []}, "nothing changed"),
        ({"checksums": []}, "no assets"),
        ({"changes": ["* a — b"]}, "em dash"),
    ],
)
def test_compose_refuses_incomplete_notes(
    overrides: dict[str, list[str]], message: str
) -> None:
    with pytest.raises(rn.NotesError, match=message):
        rn.compose(REPO, "v0.0.2", "v0.0.1", _sections(**overrides))


def _fake_api(responses: dict[str, Any]) -> Any:
    def fake(path: str, **params: str) -> Any:
        if "q" in params:
            path += ":" + params["q"]
        elif "sha" in params:
            path += "?sha=" + params["sha"]
        elif path.endswith("/tags"):
            path += "?page=" + params["page"]
        return responses[path]

    return fake


def test_build_composes_from_the_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "v0.0.2.md").write_text(GOOD, encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "pkg.whl").write_bytes(b"wheel")
    bot = _pull(6, "dependabot[bot]", "Bot")
    other = dict(_pull(5), base={"ref": "feat/v0.0.2"})
    responses = {
        f"repos/{REPO}/tags?page=1": [{"name": "v0.0.2"}, {"name": "v0.0.1"}],
        f"repos/{REPO}/compare/v0.0.1...v0.0.2": {
            "commits": [_commit("a"), _commit("b")]
        },
        f"repos/{REPO}": {"default_branch": "main"},
        f"repos/{REPO}/commits/a/pulls": [_pull(3), _pull(4, "new"), other],
        f"repos/{REPO}/commits/b/pulls": [
            _pull(4, "new"),
            bot,
            dict(_pull(9), merged_at=None),
        ],
        "search/issues:repo:owner/project is:pr is:merged author:dev": {
            "items": [{"number": 1}]
        },
        "search/issues:repo:owner/project is:pr is:merged author:new": {
            "items": [{"number": 4}]
        },
    }
    monkeypatch.setattr(rn, "_api", _fake_api(responses))
    output = tmp_path / "notes.md"
    argv = [
        "compose",
        "--repo",
        REPO,
        "--tag",
        "v0.0.2",
        "--highlights",
        str(tmp_path / "v0.0.2.md"),
        "--assets",
        str(assets),
        "--output",
        str(output),
    ]
    assert rn.main(argv) == 0
    body = output.read_text(encoding="utf-8")
    assert "pull/3\n* fix: change 4 by @new" in body
    assert "pull/6" in body and "pull/5" not in body and "pull/9" not in body
    assert "* @new made their first contribution" in body
    assert "@dependabot[bot] made" not in body and "@dev made" not in body


def test_build_without_previous_tag_lists_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "v0.0.1.md").write_text(GOOD, encoding="utf-8")
    (tmp_path / "pkg.whl").write_bytes(b"wheel")
    responses = {
        f"repos/{REPO}/tags?page=1": [{"name": "v0.0.1"}],
        f"repos/{REPO}/commits?sha=v0.0.1": [_commit("a")],
        f"repos/{REPO}": {"default_branch": "main"},
        f"repos/{REPO}/commits/a/pulls": [],
    }
    monkeypatch.setattr(rn, "_api", _fake_api(responses))
    argv = [
        "compose",
        "--repo",
        REPO,
        "--tag",
        "v0.0.1",
        "--highlights",
        str(tmp_path / "v0.0.1.md"),
        "--assets",
        str(tmp_path),
        "--output",
        str(tmp_path / "out.md"),
    ]
    assert rn.main(argv) == 0
    assert "chore: a by @dev" in (tmp_path / "out.md").read_text(
        encoding="utf-8"
    )


def test_check_reports_ok_and_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = tmp_path / "good.md"
    good.write_text(GOOD, encoding="utf-8")
    assert rn.main(["check", str(good)]) == 0
    assert "highlights OK" in capsys.readouterr().out
    assert rn.main(["check", str(tmp_path / "absent.md")]) == 1
    assert "release notes:" in capsys.readouterr().err


def test_committed_highlights_are_valid() -> None:
    files = sorted((ROOT / ".github" / "releases").glob("v*.md"))
    assert files, "no committed release highlights"
    for path in files:
        rn.validate_highlights(rn.load_highlights(path), path)


def test_tags_follow_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rn, "PAGE", 2)
    pages = {
        f"repos/{REPO}/tags?page=1": [{"name": "v0.0.3"}, {"name": "v0.0.2"}],
        f"repos/{REPO}/tags?page=2": [{"name": "v0.0.1"}],
    }
    monkeypatch.setattr(rn, "_api", _fake_api(pages))
    assert rn._tags(REPO) == ["v0.0.3", "v0.0.2", "v0.0.1"]


class _Response:
    def __init__(self, status: int, data: bytes) -> None:
        self.status = status
        self._data = data

    def read(self) -> bytes:
        return self._data


class _Connection:
    calls: ClassVar[list[tuple[str, str, str, dict[str, str]]]] = []
    reply = _Response(200, b"{}")

    def __init__(self, host: str, timeout: int) -> None:
        self.host = host

    def request(self, method: str, url: str, headers: dict[str, str]) -> None:
        self.calls.append((self.host, method, url, headers))

    def getresponse(self) -> _Response:
        return self.reply

    def close(self) -> None:
        pass


def test_api_calls_only_github_with_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setattr(rn.http.client, "HTTPSConnection", _Connection)
    _Connection.calls = []
    _Connection.reply = _Response(200, b'{"ok": true}')
    assert rn._api("search/issues", q="a b") == {"ok": True}
    host, method, url, headers = _Connection.calls[0]
    assert (host, method, url) == (
        "api.github.com",
        "GET",
        "/search/issues?q=a+b",
    )
    assert headers["Authorization"] == "Bearer secret"
    _Connection.reply = _Response(404, b"{}")
    with pytest.raises(rn.NotesError, match="HTTP 404"):
        rn._api(f"repos/{REPO}")


def test_api_needs_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(rn.NotesError, match="GH_TOKEN"):
        rn._api(f"repos/{REPO}")
