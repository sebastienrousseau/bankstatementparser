"""
Shared helpers for runnable repository examples.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CAMT_FIXTURE = REPO_ROOT / "tests" / "test_data" / "camt.053.001.02.xml"
PAIN001_FIXTURE = REPO_ROOT / "tests" / "test_data" / "pain.001.001.03.xml"
