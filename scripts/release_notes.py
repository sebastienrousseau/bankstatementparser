#!/usr/bin/env python3
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

"""Compose a GitHub release body in the suite's required format.

Every release in the suite reads, in this order:

1. ``## Highlights ⭐️``: 2 to 4 hand-written bullets, kept in
   ``.github/releases/<tag>.md`` and committed with the release.
2. ``## What's Changed``: one line per pull request merged since the
   previous tag (or per commit when there were none).
3. ``## New Contributors``: only when someone's first merged pull
   request is in this release.
4. ``## Checksums``: SHA-256 of every asset attached to the release.
5. ``**Full Changelog**``: the compare link from the previous tag.

Only the Highlights are written by hand; everything else comes from
the GitHub API and the downloaded assets, so the notes cannot drift
from what was actually released. No em dash may appear anywhere.

The same file is copied into every suite repository. Usage::

    # Before publishing: fail early if the highlights are missing.
    python3 scripts/release_notes.py check .github/releases/v0.0.32.md

    # After every asset is attached: write the full body.
    python3 scripts/release_notes.py compose --repo owner/name \\
        --tag v0.0.32 --highlights .github/releases/v0.0.32.md \\
        --assets assets/ --output notes.md

``compose`` reads the GitHub API with the token in ``GH_TOKEN`` (or
``GITHUB_TOKEN``), and only ever connects to ``api.github.com``.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

EM_DASH = "—"
HIGHLIGHT = re.compile(r"^\* \*\*[^*]+\*\*\S*\s+\S")
VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
MIN_HIGHLIGHTS, MAX_HIGHLIGHTS = 2, 4
API_HOST = "api.github.com"
PAGE = 100


class NotesError(Exception):
    """A release body cannot be composed in the required format."""


def load_highlights(path: Path) -> list[str]:
    """Return the highlight bullets, each joined onto one line.

    A line indented under a bullet continues it, so the file can wrap.
    """
    if not path.is_file():
        raise NotesError(f"{path}: highlights file is missing")
    bullets: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith((" ", "\t")) and bullets:
            bullets[-1] += " " + line.strip()
        elif line.strip():
            bullets.append(line.strip())
    return bullets


def validate_highlights(bullets: list[str], source: Path) -> None:
    """Enforce 2 to 4 ``* **Headline**: text`` bullets with no em dash."""
    if not MIN_HIGHLIGHTS <= len(bullets) <= MAX_HIGHLIGHTS:
        raise NotesError(
            f"{source}: needs {MIN_HIGHLIGHTS} to {MAX_HIGHLIGHTS} "
            f"highlights, found {len(bullets)}"
        )
    for bullet in bullets:
        if not HIGHLIGHT.match(bullet):
            raise NotesError(
                f"{source}: not a '* **Headline**: text' bullet: {bullet}"
            )
        if EM_DASH in bullet:
            raise NotesError(f"{source}: em dash in highlight: {bullet}")


def previous_tag(tag: str, tags: list[str]) -> str | None:
    """Return the highest ``vX.Y.Z`` tag below ``tag``, if any."""
    current = _version(tag)
    older = [t for t in tags if VERSION_TAG.match(t) and _version(t) < current]
    return max(older, key=_version, default=None)


def _version(tag: str) -> tuple[int, ...]:
    match = VERSION_TAG.match(tag)
    if match is None:
        raise NotesError(f"{tag}: not a vX.Y.Z tag")
    return tuple(int(part) for part in match.groups())


def change_lines(
    pulls: list[dict[str, Any]], commits: list[dict[str, Any]]
) -> list[str]:
    """Render What's Changed from pull requests, else from commits."""
    if pulls:
        return [
            f"* {p['title']} by @{p['user']['login']} in {p['html_url']}"
            for p in sorted(pulls, key=lambda p: p["number"])
        ]
    return [
        f"* {c['commit']['message'].splitlines()[0]} "
        f"by @{_login(c)} in {c['html_url']}"
        for c in commits
    ]


def _login(commit: dict[str, Any]) -> str:
    author = commit.get("author") or {}
    return str(author.get("login") or commit["commit"]["author"]["name"])


def contributor_lines(firsts: dict[str, dict[str, Any]]) -> list[str]:
    """Render New Contributors from each newcomer's first pull request."""
    return [
        f"* @{login} made their first contribution in {pull['html_url']}"
        for login, pull in sorted(firsts.items())
    ]


def checksum_lines(assets: Path) -> list[str]:
    """Return ``<sha256>  <name>`` for every file in ``assets``."""
    files = sorted(
        (f for f in assets.iterdir() if f.is_file()),
        key=lambda f: f.name.lower(),
    )
    return [
        f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}"
        for f in files
    ]


def compose(
    repo: str,
    tag: str,
    prev: str | None,
    sections: dict[str, list[str]],
) -> str:
    """Assemble the body from the rendered sections."""
    if not sections["changes"]:
        raise NotesError(f"{tag}: nothing changed since {prev}")
    if not sections["checksums"]:
        raise NotesError(f"{tag}: the release has no assets to checksum")
    parts = ["## Highlights ⭐️", "\n".join(sections["highlights"])]
    parts += ["## What's Changed", "\n".join(sections["changes"])]
    if sections["contributors"]:
        parts += ["## New Contributors", "\n".join(sections["contributors"])]
    sums = "\n".join(sections["checksums"])
    parts += [
        "## Checksums",
        f"SHA-256 of every asset attached to this release:\n\n```text\n{sums}\n```",
    ]
    link = (
        f"https://github.com/{repo}/compare/{prev}...{tag}"
        if prev
        else f"https://github.com/{repo}/commits/{tag}"
    )
    parts.append(f"**Full Changelog**: {link}")
    body = "\n\n".join(parts) + "\n"
    if EM_DASH in body:
        raise NotesError(f"{tag}: em dash in the composed notes")
    return body


def _api(path: str, **params: str) -> Any:
    """GET ``https://api.github.com/<path>`` and decode the JSON reply."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise NotesError("GH_TOKEN is not set")
    query = f"?{urlencode(params)}" if params else ""
    conn = http.client.HTTPSConnection(API_HOST, timeout=30)
    try:
        conn.request(
            "GET",
            f"/{path}{query}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "release-notes",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = conn.getresponse()
        data = response.read()
    finally:
        conn.close()
    if response.status != 200:
        raise NotesError(f"GET /{path}: HTTP {response.status}")
    return json.loads(data)


def _fetch_commits(
    repo: str, tag: str, prev: str | None
) -> list[dict[str, Any]]:
    if prev:
        return list(_api(f"repos/{repo}/compare/{prev}...{tag}")["commits"])
    return list(_api(f"repos/{repo}/commits", sha=tag, per_page=str(PAGE)))


def _fetch_pulls(
    repo: str, commits: list[dict[str, Any]], base: str
) -> list[dict[str, Any]]:
    pulls: dict[int, dict[str, Any]] = {}
    for commit in commits:
        for pull in _api(f"repos/{repo}/commits/{commit['sha']}/pulls"):
            if pull.get("merged_at") and pull["base"]["ref"] == base:
                pulls[pull["number"]] = pull
    return list(pulls.values())


def _fetch_firsts(
    repo: str, pulls: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    firsts: dict[str, dict[str, Any]] = {}
    for pull in sorted(pulls, key=lambda p: p["number"]):
        login = pull["user"]["login"]
        if login in firsts or pull["user"].get("type") == "Bot":
            continue
        found = _api(
            "search/issues",
            q=f"repo:{repo} is:pr is:merged author:{login}",
            sort="created",
            order="asc",
            per_page="1",
        )["items"]
        if found and found[0]["number"] == pull["number"]:
            firsts[login] = pull
    return firsts


def _tags(repo: str) -> list[str]:
    names: list[str] = []
    page = 1
    while True:
        batch = _api(f"repos/{repo}/tags", per_page=str(PAGE), page=str(page))
        names += [tag["name"] for tag in batch]
        if len(batch) < PAGE:
            return names
        page += 1


def build(args: argparse.Namespace) -> str:
    """Fetch everything the notes need and compose them."""
    bullets = load_highlights(args.highlights)
    validate_highlights(bullets, args.highlights)
    prev = previous_tag(args.tag, _tags(args.repo))
    commits = _fetch_commits(args.repo, args.tag, prev)
    base = _api(f"repos/{args.repo}")["default_branch"]
    pulls = _fetch_pulls(args.repo, commits, base)
    sections = {
        "highlights": bullets,
        "changes": change_lines(pulls, commits),
        "contributors": contributor_lines(_fetch_firsts(args.repo, pulls)),
        "checksums": checksum_lines(args.assets),
    }
    return compose(args.repo, args.tag, prev, sections)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the ``check`` and ``compose`` sub-commands."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate a highlights file")
    check.add_argument("highlights", type=Path)
    comp = sub.add_parser("compose", help="write the full release body")
    comp.add_argument("--repo", required=True)
    comp.add_argument("--tag", required=True)
    comp.add_argument("--highlights", type=Path, required=True)
    comp.add_argument("--assets", type=Path, required=True)
    comp.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the requested sub-command; report a format error and exit 1."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "check":
            validate_highlights(
                load_highlights(args.highlights), args.highlights
            )
            print(f"{args.highlights}: highlights OK")
        else:
            args.output.write_text(build(args), encoding="utf-8")
            print(f"wrote {args.output}")
    except NotesError as exc:
        print(f"release notes: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
