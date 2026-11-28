#!/usr/bin/env bash
# Release the bankstatementparser suite at one version: core first, then the
# thirteen member packages Suite Consistency checks, then the website
# (bankstatementparser.com). Each signed tag triggers that repository's
# publish workflow (PyPI trusted publishing; a GitHub release for the site).
#
# Phases:
#   0. Check all fifteen release PRs (waiting for running checks), merge
#      them only once every one is green, then wait for CI on each main.
#   1. Preflight every repository before tagging any of them.
#   2. Tag + push the core, wait until PyPI serves ${VERSION}.
#   3. Tag + push each member, wait until PyPI serves ${VERSION}, then
#      tag + push the website.
#   4. Run the suite consistency check, then its workflow in every
#      repository, rerunning a run that saw stale PyPI metadata.
#   5. Wait for the MCP Registry to list bankstatementparser-mcp ${VERSION}.
#   6. Wait for each release-notes job, then check every GitHub release,
#      the website's included: title "<project> ${VERSION}", the four
#      required sections, no em dash, and a checksum line for every asset.
#
# A member's first PyPI release needs a pending trusted publisher
# registered on pypi.org before its tag is pushed, or phase 3 times out.
#
# Usage: zsh scripts/release_suite.sh <version>     (e.g. 0.0.33)
#
# Each repository's release PR is the open (or already merged) PR from
# feat/v<version> into main. Safe to re-run: a merged PR is left alone
# and a repository whose tag is already on origin is skipped.
if [ -n "${ZSH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -euo pipefail

OWNER="sebastienrousseau"
VERSION="${1:-}"
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "usage: $0 <version>, e.g. 0.0.33" >&2; exit 2; }
TAG="v${VERSION}"
BASE="${HOME}/Code/Public/Python"
CORE="bankstatementparser"
MEMBERS=(
  bankstatementparser-lsp
  bankstatementparser-mcp
  bankstatementparser-loader-bai2
  bankstatementparser-loader-mt942
  bankstatementparser-writer-xlsx
  bankstatementparser-loader-bacs
  bankstatementparser-loader-camt054
  bankstatementparser-loader-cfonb
  bankstatementparser-loader-sepa
  bankstatementparser-transport-ebics
  bankstatementparser-writer-ofx
  bankstatementparser-writer-qif
  bankstatementparser-writer-swift
)
# The website ships the suite's version as a GitHub release, not on PyPI.
WEBSITE="bankstatementparser.github.io"
WEBSITE_PROJECT="bankstatementparser.com"
WEBSITE_DIR="${HOME}/Code/Public/Web/${WEBSITE}"
PYPI_WAIT_SECONDS=1800
# Core's Quality Gates alone takes about 40 minutes on main.
CI_WAIT_SECONDS=3600
# GitHub's own runs on a commit (Dependabot Updates, Dependency Graph)
# have event "dynamic": they are not the repository's CI, and a failed
# one cannot be rerun, so neither the CI wait nor the preflight counts
# them.
NOT_DYNAMIC='select(.event != "dynamic")'

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

repo_dir() {
  if [ "$1" = "${WEBSITE}" ]; then echo "${WEBSITE_DIR}"; else echo "${BASE}/$1"; fi
}

# The name in tag messages and release titles: the site's is its domain.
project_name() {
  if [ "$1" = "${WEBSITE}" ]; then echo "${WEBSITE_PROJECT}"; else echo "$1"; fi
}

remote_has_tag() {
  git -C "$(repo_dir "$1")" ls-remote --exit-code --tags origin "refs/tags/${TAG}" >/dev/null 2>&1
}

pypi_version() {
  curl -fsS "https://pypi.org/pypi/$1/json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])'
}

preflight() {
  local repo="$1" dir sha ver alerts issues bad
  dir="$(repo_dir "${repo}")"
  say "Preflight ${repo}"
  [ -d "${dir}/.git" ] || die "${dir} is not a git repository"
  git -C "${dir}" fetch -q origin --tags
  git -C "${dir}" switch -q main
  git -C "${dir}" pull -q --ff-only
  [ -z "$(git -C "${dir}" status --porcelain)" ] || die "${repo}: working tree not clean"
  sha="$(git -C "${dir}" rev-parse HEAD)"
  [ "${sha}" = "$(git -C "${dir}" rev-parse origin/main)" ] || die "${repo}: main differs from origin/main"
  if [ "${repo}" = "${WEBSITE}" ]; then
    ver="$(tr -d '[:space:]' < "${dir}/VERSION")"
    [ "${ver}" = "${VERSION}" ] || die "${repo}: VERSION is ${ver}, expected ${VERSION}"
    (cd "${dir}" && python3 scripts/release_notes.py --check) \
      || die "${repo}: release notes for ${TAG} are missing or malformed"
  else
    ver="$(python3 -c 'import tomllib,sys; d=tomllib.load(open(sys.argv[1],"rb")); print(d.get("tool",{}).get("poetry",{}).get("version") or d["project"]["version"])' "${dir}/pyproject.toml")"
    [ "${ver}" = "${VERSION}" ] || die "${repo}: pyproject version is ${ver}, expected ${VERSION}"
    python3 "${dir}/scripts/release_notes.py" check "${dir}/.github/releases/${TAG}.md" \
      || die "${repo}: release highlights for ${TAG} are missing or malformed"
  fi
  grep -q "^## \[${VERSION}\]" "${dir}/CHANGELOG.md" || die "${repo}: CHANGELOG has no ${VERSION} section"
  alerts="$(gh api "repos/${OWNER}/${repo}/dependabot/alerts?state=open" --jq length)"
  [ "${alerts}" = "0" ] || die "${repo}: ${alerts} open Dependabot alert(s)"
  issues="$(gh issue list -R "${OWNER}/${repo}" --state open --json number --jq length)"
  [ "${issues}" = "0" ] || die "${repo}: ${issues} open issue(s)"
  bad="$(gh run list -R "${OWNER}/${repo}" --commit "${sha}" --json workflowName,status,conclusion,event \
    --jq "[.[] | ${NOT_DYNAMIC}"' | select(.status != "completed" or (.conclusion != "success" and .conclusion != "skipped"))] | map("\(.workflowName)=\(.conclusion // .status)") | join(", ")')"
  [ -z "${bad}" ] || die "${repo}: CI on ${sha:0:7} not green: ${bad}"
  if remote_has_tag "${repo}"; then
    echo "${repo}: ${TAG} already on origin, will skip tagging"
  elif git -C "${dir}" rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
    die "${repo}: local ${TAG} exists but is not on origin; inspect it before continuing"
  fi
  echo "${repo}: ok at ${sha:0:7}"
}

tag_and_push() {
  local repo="$1" dir name subject
  dir="$(repo_dir "${repo}")"
  name="$(project_name "${repo}")"
  if remote_has_tag "${repo}"; then
    say "${repo}: ${TAG} already pushed, skipping"
    return
  fi
  say "Tag ${repo} ${TAG}"
  git -C "${dir}" tag -s "${TAG}" -m "${name} ${TAG}"
  git -C "${dir}" tag -v "${TAG}" >/dev/null 2>&1 || die "${repo}: ${TAG} signature does not verify"
  subject="$(git -C "${dir}" tag -l --format='%(contents:subject)' "${TAG}")"
  [ "${subject}" = "${name} ${TAG}" ] || die "${repo}: tag message is '${subject}'"
  [ "$(git -C "${dir}" rev-parse "${TAG}^{commit}")" = "$(git -C "${dir}" rev-parse origin/main)" ] \
    || die "${repo}: ${TAG} does not point at origin/main"
  git -C "${dir}" push origin "refs/tags/${TAG}"
}

wait_for_pypi() {
  local dist="$1" waited=0 got
  say "Waiting for ${dist} ${VERSION} on PyPI"
  while :; do
    got="$(pypi_version "${dist}" 2>/dev/null || true)"
    if [ "${got}" = "${VERSION}" ]; then
      echo "${dist}: PyPI serves ${got}"
      return
    fi
    [ "${waited}" -lt "${PYPI_WAIT_SECONDS}" ] \
      || die "${dist}: PyPI still serves '${got}' after ${PYPI_WAIT_SECONDS}s; check its publish workflow"
    sleep 30
    waited=$((waited + 30))
  done
}

# The site's release workflow builds ssg before it publishes, and Suite
# Consistency (phase 4) reads its latest release, so wait for it here.
wait_for_website_release() {
  local waited=0 got
  say "Waiting for the ${WEBSITE_PROJECT} ${TAG} GitHub release"
  while :; do
    got="$(gh api "repos/${OWNER}/${WEBSITE}/releases/latest" --jq .tag_name 2>/dev/null || true)"
    if [ "${got}" = "${TAG}" ]; then
      echo "${WEBSITE}: latest release is ${got}"
      return
    fi
    [ "${waited}" -lt "${PYPI_WAIT_SECONDS}" ] \
      || die "${WEBSITE}: latest release is still '${got}' after ${PYPI_WAIT_SECONDS}s; check its Release workflow"
    sleep 30
    waited=$((waited + 30))
  done
}

# ---- 0. Merge release PRs --------------------------------------------------
release_pr() {
  local repo="$1" pr
  pr="$(gh pr list -R "${OWNER}/${repo}" --base main --head "feat/v${VERSION}" --state all \
    --json number,state --jq '[.[] | select(.state != "CLOSED")][0].number // empty')"
  [ -n "${pr}" ] || die "${repo}: no open or merged PR from feat/v${VERSION} into main"
  echo "${pr}"
}

# Waits while checks are still running, then fails on any that did not
# pass. A merged PR is accepted as is.
pr_ready() {
  local repo="$1" pr="$2" state waited=0 pending failing
  state="$(gh pr view "${pr}" -R "${OWNER}/${repo}" --json state --jq .state)"
  [ "${state}" = "MERGED" ] && return
  [ "${state}" = "OPEN" ] || die "${repo} #${pr} is ${state}"
  while :; do
    pending="$(gh pr checks "${pr}" -R "${OWNER}/${repo}" --json bucket --jq '[.[] | select(.bucket == "pending")] | length')"
    [ "${pending}" = "0" ] && break
    [ "${waited}" -lt 3600 ] || die "${repo} #${pr}: ${pending} check(s) still running after 60 minutes"
    echo "${repo} #${pr}: ${pending} check(s) still running"
    sleep 60
    waited=$((waited + 60))
  done
  failing="$(gh pr checks "${pr}" -R "${OWNER}/${repo}" --json bucket --jq '[.[] | select(.bucket != "pass" and .bucket != "skipping")] | length')"
  [ "${failing}" = "0" ] || die "${repo} #${pr}: ${failing} check(s) not passing"
  echo "${repo} #${pr}: ready"
}

merge_release_pr() {
  local repo="$1" pr="$2" state
  state="$(gh pr view "${pr}" -R "${OWNER}/${repo}" --json state --jq .state)"
  [ "${state}" = "OPEN" ] && gh pr merge "${pr}" -R "${OWNER}/${repo}" --merge
  state="$(gh pr view "${pr}" -R "${OWNER}/${repo}" --json state --jq .state)"
  [ "${state}" = "MERGED" ] || die "${repo} #${pr} is ${state}, not merged"
  echo "${repo} #${pr}: merged"
}

wait_for_main_ci() {
  local repo="$1" sha waited=0
  sha="$(gh api "repos/${OWNER}/${repo}/commits/main" --jq .sha)"
  sleep 15
  while [ -n "$(gh run list -R "${OWNER}/${repo}" --commit "${sha}" --json status,event --jq ".[] | ${NOT_DYNAMIC}"' | select(.status != "completed") | .status')" ]; do
    [ "${waited}" -lt "${CI_WAIT_SECONDS}" ] || die "${repo}: CI on ${sha:0:7} still running after $((CI_WAIT_SECONDS / 60)) minutes"
    sleep 30
    waited=$((waited + 30))
  done
  echo "${repo}: CI on ${sha:0:7} finished"
}

# Every PR must exist and be green before any is merged, so a missing
# or failing member can never leave the suite half merged.
say "Checking release PRs"
declare -A PRS=()
for repo in "${CORE}" "${MEMBERS[@]}" "${WEBSITE}"; do
  PRS[${repo}]="$(release_pr "${repo}")"
  pr_ready "${repo}" "${PRS[${repo}]}"
done
say "Merging release PRs"
for repo in "${CORE}" "${MEMBERS[@]}" "${WEBSITE}"; do merge_release_pr "${repo}" "${PRS[${repo}]}"; done
say "Waiting for CI on main"
for repo in "${CORE}" "${MEMBERS[@]}" "${WEBSITE}"; do wait_for_main_ci "${repo}"; done

# ---- 1. Preflight ---------------------------------------------------------
for repo in "${CORE}" "${MEMBERS[@]}" "${WEBSITE}"; do preflight "${repo}"; done

# ---- 2. Core --------------------------------------------------------------
tag_and_push "${CORE}"
wait_for_pypi "${CORE}"

# ---- 3. Members -----------------------------------------------------------
for repo in "${MEMBERS[@]}"; do tag_and_push "${repo}"; done
for repo in "${MEMBERS[@]}"; do wait_for_pypi "${repo}"; done
tag_and_push "${WEBSITE}"
wait_for_website_release

# ---- 4. Suite Consistency -------------------------------------------------
say "Suite consistency"
# PyPI's JSON API sits behind a CDN cache, so a request moments after
# wait_for_pypi saw the new version can still get a stale copy (0.0.32
# release failed here once with every package already published). Retry the
# check for up to 10 minutes before calling it a real disagreement.
waited=0
until python3 "${BASE}/${CORE}/scripts/check_suite_consistency.py"; do
  [ "${waited}" -lt 600 ] || die "suite still disagrees after 600s; check the publish workflows"
  echo "PyPI may still be serving cached metadata; retrying in 30s"
  sleep 30
  waited=$((waited + 30))
done
# The workflow runs hit the same PyPI cache from GitHub's runners, so a
# run can still see the old version after the local check has passed
# (0.0.33: core's and lsp's runs failed and passed on rerun). Wait for
# each run and rerun a failure, up to 5 attempts a minute apart.
declare -A SUITE_RUNS=()
for repo in "${CORE}" "${MEMBERS[@]}"; do
  url="$(gh workflow run suite-consistency.yml -R "${OWNER}/${repo}" --ref main 2>&1 | grep -o 'https://[^ ]*/actions/runs/[0-9]*' || true)"
  [ -n "${url}" ] || die "${repo}: could not start Suite Consistency"
  SUITE_RUNS[${repo}]="${url##*/}"
  echo "${repo}: Suite Consistency started (${url})"
done
for repo in "${CORE}" "${MEMBERS[@]}"; do
  run="${SUITE_RUNS[${repo}]}" attempt=1
  until gh run watch "${run}" -R "${OWNER}/${repo}" --exit-status > /dev/null 2>&1; do
    [ "${attempt}" -lt 5 ] || die "${repo}: Suite Consistency failed ${attempt} times; see https://github.com/${OWNER}/${repo}/actions/runs/${run}"
    echo "${repo}: Suite Consistency failed (attempt ${attempt}); rerunning in 60s"
    sleep 60
    gh run rerun "${run}" -R "${OWNER}/${repo}"
    sleep 15
    attempt=$((attempt + 1))
  done
  echo "${repo}: Suite Consistency passed"
done

# ---- 5. MCP Registry --------------------------------------------------------
NAME="io.github.${OWNER}/bankstatementparser-mcp"
say "Waiting for ${NAME} ${VERSION} on the MCP Registry"
waited=0
until curl -fsS "https://registry.modelcontextprotocol.io/v0/servers?search=${NAME}" \
    | jq -r --arg n "${NAME}" '.servers[] | .server // . | select(.name == $n) | .version' \
    | grep -qx "${VERSION}"; do
  [ "${waited}" -lt 900 ] || die "registry does not list ${VERSION}; check the Publish to MCP Registry run"
  sleep 30
  waited=$((waited + 30))
done
echo "${NAME} ${VERSION} is on the registry"

# ---- 6. Release titles and notes ------------------------------------------
# The release-notes job runs last in each publish workflow; until it has
# run, the body holds only the highlights placeholder.
say "GitHub release titles and notes"
check_release() {
  python3 - "$1" "$2" <<'PYCHECK'
import json, sys
repo, rel = sys.argv[1], json.loads(sys.argv[2])
body = rel["body"]
want = ["## Highlights \u2b50\ufe0f", "## What's Changed", "## Checksums", "**Full Changelog**: "]
missing = [w for w in want if w not in body]
# The site's notes list assets as "./<name>"; the packages' as "<name>".
unsummed = [a["name"] for a in rel["assets"]
            if f"  {a['name']}\n" not in body and f"  ./{a['name']}\n" not in body]
problems = []
if missing: problems.append(f"missing {missing}")
if unsummed: problems.append(f"no checksum for {unsummed}")
if "\u2014" in body: problems.append("em dash in body")
print("; ".join(problems))
PYCHECK
}
for repo in "${CORE}" "${MEMBERS[@]}" "${WEBSITE}"; do
  waited=0
  while :; do
    rel="$(gh release view "${TAG}" -R "${OWNER}/${repo}" --json name,body,assets 2>/dev/null || true)"
    if [ -n "${rel}" ] && grep -q '## Checksums' <<<"${rel}"; then break; fi
    [ "${waited}" -lt 1200 ] || die "${repo}: release notes for ${TAG} were never written; check the 'Write the release notes' job"
    sleep 30
    waited=$((waited + 30))
  done
  title="$(jq -r .name <<<"${rel}")"
  [ "${title}" = "$(project_name "${repo}") ${VERSION}" ] || die "${repo}: release title is '${title}'"
  problems="$(check_release "${repo}" "${rel}")"
  [ -z "${problems}" ] || die "${repo}: ${problems}"
  echo "${repo}: ${title}, notes complete"
done

say "Done. Tell Claude: released ${VERSION}"
