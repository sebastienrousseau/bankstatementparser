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

"""Tests for the GitHub request in ``scripts/check_suite_consistency.py``.

Anonymous GitHub API calls share a limit of 60 an hour per address, and
CI runners share addresses, so the website lookup must authenticate when
the workflow provides a token.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_suite_consistency",
        ROOT / "scripts" / "check_suite_consistency.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


csc = _load()


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replace urlopen with a stub that records what it was asked for."""
    seen: list[Any] = []

    def fake_urlopen(request: Any, timeout: float) -> io.BytesIO:
        seen.append(request)
        return io.BytesIO(json.dumps({"tag_name": "v0.0.36"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


def test_website_lookup_sends_the_workflow_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    seen = _capture(monkeypatch)

    assert csc.website_version() == "0.0.36"
    (request,) = seen
    assert isinstance(request, urllib.request.Request)
    assert request.full_url == (
        "https://api.github.com/repos/"
        "sebastienrousseau/bankstatementparser.github.io/releases/latest"
    )
    assert request.get_header("Authorization") == "Bearer test-token"


def test_website_lookup_without_a_token_stays_anonymous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    seen = _capture(monkeypatch)

    assert csc.website_version() == "0.0.36"
    (request,) = seen
    assert isinstance(request, urllib.request.Request)
    assert request.get_header("Authorization") is None
