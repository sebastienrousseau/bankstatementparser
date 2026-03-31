#!/usr/bin/env python3
"""Fail CI when GitHub reports unsigned or unverified commits."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API_ROOT = "https://api.github.com"
VALID_REASONS = {"valid"}
NULL_SHA = "0" * 40


def github_get_json(url: str, token: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise RuntimeError(
            f"Refusing to call unexpected GitHub API URL: {url}"
        )

    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request) as response:  # nosec B310
            return cast(dict[str, Any], json.load(response))
    except HTTPError as exc:  # pragma: no cover
        raise RuntimeError(
            f"GitHub API request failed: {url} ({exc.code})"
        ) from exc


def compare_commits(
    repo: str,
    base: str,
    head: str,
    token: str,
) -> list[dict[str, Any]]:
    compare = github_get_json(
        f"{API_ROOT}/repos/{repo}/compare/{base}...{head}",
        token,
    )
    commits = cast(list[dict[str, Any]], compare.get("commits", []))
    if not commits:
        head_commit = github_get_json(
            f"{API_ROOT}/repos/{repo}/commits/{head}",
            token,
        )
        commits = [head_commit]
    return commits


def commits_for_initial_push(
    repo: str,
    event: dict[str, Any],
    token: str,
) -> list[dict[str, Any]]:
    commits = []
    for commit in cast(list[dict[str, Any]], event.get("commits", [])):
        sha = commit.get("id")
        if not sha:
            continue
        commits.append(
            github_get_json(
                f"{API_ROOT}/repos/{repo}/commits/{sha}", token
            )
        )

    if commits:
        return commits

    head_sha = cast(str, event["after"])
    return [
        github_get_json(
            f"{API_ROOT}/repos/{repo}/commits/{head_sha}", token
        )
    ]


def commit_range_from_event(
    event_name: str,
    event: dict[str, Any],
) -> tuple[str, str]:
    if event_name == "pull_request":
        pull_request = event["pull_request"]
        return pull_request["base"]["sha"], pull_request["head"]["sha"]
    if event_name == "push":
        return event["before"], event["after"]
    raise RuntimeError(
        "Unsupported event for signature verification: "
        f"{event_name}. Use --base-sha and --head-sha to override."
    )


def commits_from_event(
    repo: str,
    event_name: str,
    event: dict[str, Any],
    token: str,
) -> list[dict[str, Any]]:
    if event_name == "push" and event.get("before") == NULL_SHA:
        return commits_for_initial_push(repo, event, token)

    base_sha, head_sha = commit_range_from_event(event_name, event)
    return compare_commits(repo, base_sha, head_sha, token)


def verify_commits(commits: Iterable[dict[str, Any]]) -> list[str]:
    failures = []
    for commit in commits:
        verification = commit.get("commit", {}).get("verification", {})
        verified = verification.get("verified", False)
        reason = verification.get("reason", "unknown")
        if not verified or reason not in VALID_REASONS:
            failures.append(
                f"{commit['sha']}: verified={verified}, reason={reason}"
            )
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that all commits in the current GitHub event are signed."
    )
    parser.add_argument(
        "--repo", default=os.environ.get("GITHUB_REPOSITORY")
    )
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument(
        "--event-name", default=os.environ.get("GITHUB_EVENT_NAME")
    )
    parser.add_argument(
        "--event-path",
        type=Path,
        default=Path(os.environ.get("GITHUB_EVENT_PATH", "")),
    )
    parser.add_argument(
        "--token", default=os.environ.get("GITHUB_TOKEN")
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.repo or not args.token:
        print(
            "GITHUB_REPOSITORY and GITHUB_TOKEN are required.",
            file=sys.stderr,
        )
        return 2

    if args.base_sha and args.head_sha:
        base_sha = args.base_sha
        head_sha = args.head_sha
        commits = compare_commits(
            args.repo, base_sha, head_sha, args.token
        )
    else:
        if not args.event_name or not args.event_path.exists():
            print(
                "Either --base-sha/--head-sha or a valid GitHub event context is required.",
                file=sys.stderr,
            )
            return 2
        event = json.loads(args.event_path.read_text(encoding="utf-8"))
        commits = commits_from_event(
            args.repo, args.event_name, event, args.token
        )
    failures = verify_commits(commits)
    if failures:
        print("Unsigned or unverified commits detected:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print(f"Verified GitHub signatures for {len(commits)} commits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
