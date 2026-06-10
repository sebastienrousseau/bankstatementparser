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
#
# See the License for the specific language governing permissions and
# limitations under the License.

.PHONY: install install-all install-hooks dist release test lint typecheck security verify clean

# ----- Local development -----------------------------------------------------

install:
	poetry install --with dev

# Wire the pre-commit hook so `make verify` runs before every commit.
# One-time setup per clone — idempotent, safe to re-run.
install-hooks:
	git config core.hooksPath .githooks
	@echo "pre-commit hook installed (.githooks/pre-commit)"

# Install with all hybrid extras (litellm, pypdf, pdfplumber, pypdfium2).
install-all:
	poetry install --with dev -E hybrid-vision -E hybrid-plus -E polars

# ----- Pre-PR validation gates ----------------------------------------------

test:
	poetry run pytest --cov=bankstatementparser

lint:
	poetry run ruff check bankstatementparser tests examples scripts

typecheck:
	poetry run mypy bankstatementparser

security:
	poetry run bandit -r bankstatementparser examples scripts -c pyproject.toml

# Run every gate the GitHub Actions pipeline runs, in the same order.
verify: lint typecheck test security

# ----- Build & release ------------------------------------------------------

clean:
	rm -rf ./dist ./build ./*.egg-info
	rm -rf ./htmlcov ./coverage.xml ./.coverage
	rm -rf ./.pytest_cache ./.ruff_cache ./.mypy_cache ./.hypothesis ./.benchmarks
	find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} +

# Produce sdist + wheel via Poetry. Replaces the legacy
# `python3 setup.py sdist bdist_wheel` flow that drifted out of sync with
# the Poetry-managed pyproject.toml.
dist: clean
	poetry build

# Tag the current version, push, then publish to PyPI. Aborts if the
# working tree is dirty. The tag is signed with the configured signing
# key (commit.gpgsign / tag.gpgSign / gpg.format must be set — see
# CONTRIBUTING.md).
release: dist
	git diff --exit-code
	git diff --cached --exit-code
	@VERSION=$$(poetry version --short); \
	  git tag -s "v$$VERSION" -m "Release v$$VERSION" && \
	  git push && \
	  git push origin "v$$VERSION" && \
	  poetry publish