#!/usr/bin/env bash
# Release the bankstatementparser suite at one version, core first, then the
# five members Suite Consistency checks. Each signed tag triggers that
# repository's publish workflow (PyPI trusted publishing).
#
# Phases:
#   0. Check all six release PRs (waiting for running checks), merge
#      them only once every one is green, then wait for CI on each main.
#   1. Preflight every repository before tagging any of them.
#   2. Tag + push the core, wait until PyPI serves ${VERSION}.
#   3. Tag + push each member, wait until PyPI serves ${VERSION}.
#   4. Run the suite consistency check and re-run its workflow everywhere.
#   5. Wait for the MCP Registry to list bankstatementparser-mcp ${VERSION}.
#   6. Wait for each release-notes job, then check every GitHub release:
#      title "<project> ${VERSION}", the four required sections, no em dash,
#      and a checksum line for every attached asset.
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
)
PYPI_WAIT_SECONDS=1800

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

remote_has_tag() {
  git -C "${BASE}/$1" ls-remote --exit-code --tags origin "refs/tags/${TAG}" >/dev/null 2>&1
}

pypi_version() {
  curl -fsS "https://pypi.org/pypi/$1/json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])'
}

preflight() {
  local repo="$1" dir="${BASE}/$1" sha ver alerts issues bad
  say "Preflight ${repo}"
  [ -d "${dir}/.git" ] || die "${dir} is not a git repository"
  git -C "${dir}" fetch -q origin --tags
  git -C "${dir}" switch -q main
  git -C "${dir}" pull -q --ff-only
  [ -z "$(git -C "${dir}" status --porcelain)" ] || die "${repo}: working tree not clean"
  sha="$(git -C "${dir}" rev-parse HEAD)"
  [ "${sha}" = "$(git -C "${dir}" rev-parse origin/main)" ] || die "${repo}: main differs from origin/main"
  ver="$(python3 -c 'import tomllib,sys; d=tomllib.load(open(sys.argv[1],"rb")); print(d.get("tool",{}).get("poetry",{}).get("version") or d["project"]["version"])' "${dir}/pyproject.toml")"
  [ "${ver}" = "${VERSION}" ] || die "${repo}: pyproject version is ${ver}, expected ${VERSION}"
  grep -q "^## \[${VERSION}\]" "${dir}/CHANGELOG.md" || die "${repo}: CHANGELOG has no ${VERSION} section"
  python3 "${dir}/scripts/release_notes.py" check "${dir}/.github/releases/${TAG}.md" \
    || die "${repo}: release highlights for ${TAG} are missing or malformed"
  alerts="$(gh api "repos/${OWNER}/${repo}/dependabot/alerts?state=open" --jq length)"
  [ "${alerts}" = "0" ] || die "${repo}: ${alerts} open Dependabot alert(s)"
  issues="$(gh issue list -R "${OWNER}/${repo}" --state open --json number --jq length)"
  [ "${issues}" = "0" ] || die "${repo}: ${issues} open issue(s)"
  bad="$(gh run list -R "${OWNER}/${repo}" --commit "${sha}" --json workflowName,status,conclusion \
    --jq '[.[] | select(.status != "completed" or (.conclusion != "success" and .conclusion != "skipped"))] | map("\(.workflowName)=\(.conclusion // .status)") | join(", ")')"
  [ -z "${bad}" ] || die "${repo}: CI on ${sha:0:7} not green: ${bad}"
  if remote_has_tag "${repo}"; then
    echo "${repo}: ${TAG} already on origin, will skip tagging"
  elif git -C "${dir}" rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
    die "${repo}: local ${TAG} exists but is not on origin; inspect it before continuing"
  fi
  echo "${repo}: ok at ${sha:0:7}"
}

tag_and_push() {
  local repo="$1" dir="${BASE}/$1" subject
  if remote_has_tag "${repo}"; then
    say "${repo}: ${TAG} already pushed, skipping"
    return
  fi
  say "Tag ${repo} ${TAG}"
  git -C "${dir}" tag -s "${TAG}" -m "${repo} ${TAG}"
  git -C "${dir}" tag -v "${TAG}" >/dev/null 2>&1 || die "${repo}: ${TAG} signature does not verify"
  subject="$(git -C "${dir}" tag -l --format='%(contents:subject)' "${TAG}")"
  [ "${subject}" = "${repo} ${TAG}" ] || die "${repo}: tag message is '${subject}'"
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
  while [ -n "$(gh run list -R "${OWNER}/${repo}" --commit "${sha}" --json status --jq '.[] | select(.status != "completed") | .status')" ]; do
    [ "${waited}" -lt 1800 ] || die "${repo}: CI on ${sha:0:7} still running after 30 minutes"
    sleep 30
    waited=$((waited + 30))
  done
  echo "${repo}: CI on ${sha:0:7} finished"
}

# Every PR must exist and be green before any is merged, so a missing
# or failing member can never leave the suite half merged.
say "Checking release PRs"
declare -A PRS=()
for repo in "${CORE}" "${MEMBERS[@]}"; do
  PRS[${repo}]="$(release_pr "${repo}")"
  pr_ready "${repo}" "${PRS[${repo}]}"
done
say "Merging release PRs"
for repo in "${CORE}" "${MEMBERS[@]}"; do merge_release_pr "${repo}" "${PRS[${repo}]}"; done
say "Waiting for CI on main"
for repo in "${CORE}" "${MEMBERS[@]}"; do wait_for_main_ci "${repo}"; done

# ---- 1. Preflight ---------------------------------------------------------
for repo in "${CORE}" "${MEMBERS[@]}"; do preflight "${repo}"; done

# ---- 2. Core --------------------------------------------------------------
tag_and_push "${CORE}"
wait_for_pypi "${CORE}"

# ---- 3. Members -----------------------------------------------------------
for repo in "${MEMBERS[@]}"; do tag_and_push "${repo}"; done
for repo in "${MEMBERS[@]}"; do wait_for_pypi "${repo}"; done

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
for repo in "${CORE}" "${MEMBERS[@]}"; do
  gh workflow run suite-consistency.yml -R "${OWNER}/${repo}" --ref main
  echo "${repo}: Suite Consistency re-run requested"
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
unsummed = [a["name"] for a in rel["assets"] if f"  {a['name']}\n" not in body]
problems = []
if missing: problems.append(f"missing {missing}")
if unsummed: problems.append(f"no checksum for {unsummed}")
if "\u2014" in body: problems.append("em dash in body")
print("; ".join(problems))
PYCHECK
}
for repo in "${CORE}" "${MEMBERS[@]}"; do
  waited=0
  while :; do
    rel="$(gh release view "${TAG}" -R "${OWNER}/${repo}" --json name,body,assets 2>/dev/null || true)"
    if [ -n "${rel}" ] && grep -q '## Checksums' <<<"${rel}"; then break; fi
    [ "${waited}" -lt 1200 ] || die "${repo}: release notes for ${TAG} were never written; check the 'Write the release notes' job"
    sleep 30
    waited=$((waited + 30))
  done
  title="$(jq -r .name <<<"${rel}")"
  [ "${title}" = "${repo} ${VERSION}" ] || die "${repo}: release title is '${title}'"
  problems="$(check_release "${repo}" "${rel}")"
  [ -z "${problems}" ] || die "${repo}: ${problems}"
  echo "${repo}: ${title}, notes complete"
done

say "Done. Tell Claude: released ${VERSION}"
