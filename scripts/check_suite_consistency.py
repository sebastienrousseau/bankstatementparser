#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sebastien Rousseau <sebastian.rousseau@gmail.com>
# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Check the published bankstatementparser suite agrees with its own policy.

The suite ships one version number across every package. That is easy to
state and easy to let slip, because nothing breaks when it does: a member
left a release behind still installs, still imports, still passes its own
tests. It just quietly means something different from what it says.

Two failures this catches, both of which had already happened here:

* **A member left behind.** The bankstatementparser packages disagreed:
  0.0.14, 0.0.15, 0.0.17, 0.0.16, 0.0.16 and 0.0.15
  -- different numbers for one suite.

* **A version bumped in the tree and never released.** Three repositories
  in the wider suite have done this, each time stranding a `cryptography`
  advisory floor that reached nobody. Nothing fails when it happens; only
  PyPI disagrees, and only if somebody looks. This looks.

Exits non-zero when the suite disagrees with itself, so a schedule turns
into a notification rather than a report nobody opens.

Usage:
    python3 scripts/check_suite_consistency.py
    python3 scripts/check_suite_consistency.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the 3.10 floor
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent

#: Every published member of the bankstatementparser suite. The core is first.
MEMBERS = (
    "bankstatementparser",
    "bankstatementparser-lsp",
    "bankstatementparser-mcp",
    "bankstatementparser-loader-bai2",
    "bankstatementparser-loader-mt942",
    "bankstatementparser-writer-xlsx",
)

TIMEOUT = 30


def published_version(distribution: str) -> str | None:
    """The newest version of ``distribution`` on PyPI, or None."""
    # The name is quoted and the scheme is checked before the request.
    # Both are belt-and-braces here -- MEMBERS is a literal tuple in this
    # file -- but urlopen honours file:// and custom schemes, so a URL
    # reaching it unchecked is worth refusing on principle rather than on
    # the argument that today's input happens to be safe.
    url = "https://pypi.org/pypi/" + quote(distribution, safe="") + "/json"
    if not url.startswith("https://pypi.org/"):  # pragma: no cover
        raise ValueError(f"refusing to fetch a non-PyPI URL: {url}")
    try:
        # B310 is satisfied by the scheme check above. Only bandit's
        # suppression is used: ruff's S rules are not enabled in most of
        # these repositories, and an unused noqa is itself a lint error
        # (RUF100). The reason sits here rather than inline because
        # bandit parses words following "nosec" as test ids.
        opened = urllib.request.urlopen(url, timeout=TIMEOUT)  # nosec B310
        with opened as response:
            return str(json.load(response)["info"]["version"])
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
        return None


def tree_version() -> str:
    """The version this checkout declares."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    poetry = data.get("tool", {}).get("poetry", {})
    return str(poetry.get("version") or data["project"]["version"])


def check() -> tuple[list[str], dict[str, object]]:
    """Return (problems, report)."""
    problems: list[str] = []
    tree = tree_version()
    published = {name: published_version(name) for name in MEMBERS}

    core_published = published[MEMBERS[0]]

    # 1. The tree must not disagree with what was released. A bump that
    #    was never tagged looks exactly like this and nothing else
    #    notices.
    if core_published and core_published != tree:
        problems.append(
            f"{MEMBERS[0]}: tree is {tree} but PyPI has {core_published}. "
            f"Either the release was never tagged, or the tree is behind."
        )

    # 2. Every member ships the core's number.
    for name, version in published.items():
        if version is None:
            problems.append(f"{name}: could not read PyPI")
        elif core_published and version != core_published:
            problems.append(
                f"{name}: published {version}, but the suite is at "
                f"{core_published}"
            )

    return problems, {
        "tree": tree,
        "published": published,
        "problems": problems,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    problems, report = check()
    if args.json:
        json.dump(report, sys.stdout, indent=1)
        print()
    else:
        print(f"tree version: {report['tree']}")
        for name, version in report["published"].items():  # type: ignore[union-attr]
            print(f"  {name:34} {version}")
        if problems:
            print("\nproblems:")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print("\nthe suite agrees with itself")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
