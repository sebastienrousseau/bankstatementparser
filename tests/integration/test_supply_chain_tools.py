"""Integration tests for supply-chain automation scripts."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY_SIGNATURES_PATH = (
    ROOT / "scripts" / "verify_github_commit_signatures.py"
)


def load_signature_module():
    spec = spec_from_file_location(
        "verify_github_commit_signatures",
        VERIFY_SIGNATURES_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_sbom_script(tmp_path: Path) -> None:
    sbom_path = tmp_path / "sbom.json"
    report_path = tmp_path / "dependency-report.md"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_sbom.py"),
            "--output",
            str(sbom_path),
            "--markdown-output",
            str(report_path),
        ],
        check=True,
        cwd=ROOT,
    )

    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert (
        sbom["metadata"]["component"]["name"] == "bankstatementparser"
    )
    assert sbom["components"]
    assert report_path.read_text(encoding="utf-8").startswith(
        "# Dependency Report"
    )


def test_generate_checksums_script(tmp_path: Path) -> None:
    artifact_one = tmp_path / "artifact-one.txt"
    artifact_two = tmp_path / "artifact-two.txt"
    artifact_one.write_text("alpha", encoding="utf-8")
    artifact_two.write_text("beta", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_checksums.py"),
            str(tmp_path),
        ],
        check=True,
        cwd=ROOT,
    )

    checksum_file = tmp_path / "SHA256SUMS"
    content = checksum_file.read_text(encoding="utf-8")
    assert "artifact-one.txt" in content
    assert "artifact-two.txt" in content


def test_verify_locked_hashes_script() -> None:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_locked_hashes.py"),
        ],
        check=True,
        cwd=ROOT,
    )


def test_commit_signature_script_rejects_unexpected_urls() -> None:
    module = load_signature_module()
    try:
        module.github_get_json("https://example.com/commits", "token")
    except RuntimeError as exc:
        assert "unexpected GitHub API URL" in str(exc)
    else:  # pragma: no cover
        raise AssertionError(
            "Expected URL allowlist enforcement to fail"
        )


def test_commit_signature_script_uses_event_commits_for_initial_push() -> (
    None
):
    module = load_signature_module()
    calls: list[str] = []

    def fake_github_get_json(url: str, token: str) -> dict[str, object]:
        calls.append(url)
        return {
            "sha": url.rsplit("/", 1)[-1],
            "commit": {
                "verification": {"verified": True, "reason": "valid"}
            },
        }

    module.github_get_json = fake_github_get_json
    commits = module.commits_from_event(
        "sebastienrousseau/bankstatementparser",
        "push",
        {
            "before": "0" * 40,
            "after": "b" * 40,
            "commits": [{"id": "a" * 40}, {"id": "b" * 40}],
        },
        "token",
    )

    assert [commit["sha"] for commit in commits] == ["a" * 40, "b" * 40]
    assert calls == [
        "https://api.github.com/repos/sebastienrousseau/bankstatementparser/commits/"
        + ("a" * 40),
        "https://api.github.com/repos/sebastienrousseau/bankstatementparser/commits/"
        + ("b" * 40),
    ]


def test_commit_signature_script_falls_back_to_after_sha_on_initial_push() -> (
    None
):
    module = load_signature_module()
    calls: list[str] = []

    def fake_github_get_json(url: str, token: str) -> dict[str, object]:
        calls.append(url)
        return {
            "sha": url.rsplit("/", 1)[-1],
            "commit": {
                "verification": {"verified": True, "reason": "valid"}
            },
        }

    module.github_get_json = fake_github_get_json
    commits = module.commits_from_event(
        "sebastienrousseau/bankstatementparser",
        "push",
        {
            "before": "0" * 40,
            "after": "c" * 40,
            "commits": [],
        },
        "token",
    )

    assert [commit["sha"] for commit in commits] == ["c" * 40]
    assert calls == [
        "https://api.github.com/repos/sebastienrousseau/bankstatementparser/commits/"
        + ("c" * 40)
    ]
