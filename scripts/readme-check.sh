#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 OR MIT
#
# Shared by every bankstatementparser suite repository, byte for byte;
# adapted from askiso's scripts/readme-check.sh for Python.
#
# Fail unless README.md follows the portfolio README template
# (~/Code/README-TEMPLATE.md, AGENTS.md §7.3): an SPDX comment on line 1, a
# centred plain-text h1, the template's second-level headings in the
# template's order, no unresolved {{UPPER_SNAKE_CASE}} variable outside
# code, the template's six-badge row (all for-the-badge, the toolchain badge
# naming pyproject.toml's Python floor), and the demo block showing a
# committed .github/demo.gif directly under it (§7.1.1). The heading list is the
# template's; update both together.
#
#   scripts/readme-check.sh [README.md]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
readme="${1:-README.md}"
[ -f "${readme}" ] || { echo "readme-check: ${readme} not found" >&2; exit 1; }

spdx=$(sed -n '1s|^<!-- SPDX-License-Identifier: \(.*\) -->$|\1|p' "${readme}")
[ -n "${spdx}" ] || { echo "readme-check: line 1 is not <!-- SPDX-License-Identifier: ... -->" >&2; exit 1; }

project=$(sed -n 's|^<h1 align="center">\([^<]*\)</h1>$|\1|p' "${readme}" | head -1)
[ -n "${project}" ] || { echo "readme-check: no centred plain-text <h1 align=\"center\">name</h1>" >&2; exit 1; }

expected=$(cat <<LIST
Contents
Install
Requirements
Quick Start
The ${project} ecosystem
Capabilities at a glance
Ecosystem comparison
Benchmarks
Features
Configuration
Examples
When not to use ${project}
Development
Security
Documentation
Stability guarantees
License
LIST
)

# Second-level headings and template tokens, both outside fenced code.
outside_code=$(awk '/^[[:space:]]*(```|~~~)/ { fence = !fence; next } !fence' "${readme}")
actual=$(sed -n 's/^## //p' <<<"${outside_code}")
if [ "${actual}" != "${expected}" ]; then
  echo "readme-check: second-level headings differ from the template:" >&2
  diff <(echo "${expected}") <(echo "${actual}") >&2 || true
  exit 1
fi

# Inline code is content too: strip it before looking for variables.
# shellcheck disable=SC2001,SC2016 # a regex substitution with literal backticks
tokens=$(sed 's/`[^`]*`//g' <<<"${outside_code}" | grep -oE '\{\{ *[A-Z][A-Z0-9_]* *\}\}' || true)
[ -z "${tokens}" ] || { echo "readme-check: unresolved template variables: ${tokens}" >&2; exit 1; }

# The badge row: every shields.io image, in the template's order, by alt text.
badges=$(grep -o '<img src="https://img.shields.io/[^"]*" alt="[^"]*"' "${readme}" || true)
alts=$(grep -o 'alt="[^"]*"' <<<"${badges}" | cut -d'"' -f2 || true)
# The Python floor: the lower bound of the poetry or PEP 621 constraint.
floor=$(sed -nE 's/^(python|requires-python) *= *"[^0-9]*([0-9]+\.[0-9]+).*/\2/p' pyproject.toml | head -1)
[ -n "${floor}" ] || { echo "readme-check: no Python floor in pyproject.toml" >&2; exit 1; }
expected_alts=$(cat <<LIST
Build
Registry
Docs
OpenSSF Scorecard
License: ${spdx}
Python ${floor}+
LIST
)
if [ "${alts}" != "${expected_alts}" ]; then
  echo "readme-check: the badge row differs from the template's six badges:" >&2
  diff <(echo "${expected_alts}") <(echo "${alts}") >&2 || true
  exit 1
fi
if grep -v 'style=for-the-badge' <<<"${badges}" >&2; then
  echo "readme-check: every badge must be style=for-the-badge" >&2
  exit 1
fi
grep -q "img.shields.io/badge/python-${floor}%2B-" <<<"${badges}" || {
  echo "readme-check: the toolchain badge does not state pyproject.toml's floor, ${floor}" >&2
  exit 1
}

# The visual demo (AGENTS.md §7.1.1): the template's demo block directly
# under the badge row, with alt text, pointing at a GIF that is committed.
# The template's absolute raw URL, so the GIF also renders on PyPI.
demo_block='^  <img src="https://raw\.githubusercontent\.com/[^/"]*/[^/"]*/main/\.github/demo\.gif" alt="[^"][^"]*" width="100%" />$'
demo_line=$(grep -n "${demo_block}" "${readme}" | head -1 | cut -d: -f1 || true)
last_badge=$(grep -n '<img src="https://img.shields.io/' "${readme}" | tail -1 | cut -d: -f1 || true)
contents=$(grep -n '^## Contents$' "${readme}" | head -1 | cut -d: -f1 || true)
if [ -z "${demo_line}" ] || [ -z "${last_badge}" ] || [ -z "${contents}" ] ||
  [ "${demo_line}" -lt "${last_badge}" ] || [ "${demo_line}" -gt "${contents}" ]; then
  echo "readme-check: no demo block under the badge row:" >&2
  echo '  <img src="https://raw.githubusercontent.com/<owner>/<repo>/main/.github/demo.gif" alt="what the demo shows" width="100%" />' >&2
  exit 1
fi
[ -f .github/demo.gif ] || { echo "readme-check: .github/demo.gif is missing; run make demo" >&2; exit 1; }

# Every relative link must name a file that exists: the template links
# docs it assumes, and a README must not point at one this repository lacks.
missing=0
while IFS= read -r target; do
  path=${target%%#*}
  [ -z "${path}" ] && continue
  if [ ! -e "${path}" ]; then
    echo "readme-check: links to ${path}, which does not exist" >&2
    missing=1
  fi
done < <(grep -oE '\]\([^)#:]+(#[^)]*)?\)|(href|src)="[^"#:]+"' <<<"${outside_code}" |
  sed -E 's/^\]\(//; s/\)$//; s/^(href|src)="//; s/"$//' | sort -u)
[ "${missing}" -eq 0 ] || exit 1

echo "readme-check: ${readme} follows the template (${project})"
