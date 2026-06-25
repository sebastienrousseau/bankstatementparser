"""
Example: validate a file path before parsing.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bankstatementparser import (  # noqa: E402
    InputValidator,
    ValidationError,
)
from common import CAMT_FIXTURE  # noqa: E402


def main() -> None:
    """Validate a legitimate file path and reject a dangerous one."""
    validator = InputValidator()

    # Validate a legitimate file
    validated = validator.validate_input_file_path(str(CAMT_FIXTURE))
    print(f"Validated: {validated}")

    # Demonstrate rejection of a dangerous path
    try:
        validator.validate_input_file_path("../../etc/passwd")
    except (ValidationError, FileNotFoundError) as exc:
        print(f"Rejected: {exc}")


if __name__ == "__main__":
    main()
