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

"""Additional bank statement parsers and format detection helpers."""

from __future__ import annotations

from pathlib import Path

from .base_parser import BankStatementParser
from .camt_parser import CamtParser
from .camt_reports import Camt052Parser, Camt054Parser
from .input_validator import ValidationError
from .pain001_parser import Pain001Parser
from .parsers import (
    CSV_COLUMN_GROUPS,
    Bai2Parser,
    CsvStatementParser,
    Mt940Parser,
    OfxParser,
    QfxParser,
    _amount_or_zero,
    _grouped_summaries,
    _normalize_delimiters,
    _normalized_name,
    _parse_amount,
    _read_validated_text,
    _require_amount,
    _summary_text,
)
from .plugins import get_registered_loaders

__all__ = [
    "CSV_COLUMN_GROUPS",
    "Bai2Parser",
    "Camt052Parser",
    "Camt054Parser",
    "CsvStatementParser",
    "Mt940Parser",
    "OfxParser",
    "QfxParser",
    "_amount_or_zero",
    "_grouped_summaries",
    "_normalize_delimiters",
    "_normalized_name",
    "_parse_amount",
    "_read_validated_text",
    "_require_amount",
    "_summary_text",
    "create_parser",
    "detect_statement_format",
]


def _detect_by_suffix(suffix: str) -> str | None:
    """Detect statement format from file extension."""
    if suffix == ".csv":
        return "csv"
    if suffix in {".ofx", ".qfx"}:
        return "ofx"
    if suffix in {".mt940", ".sta"}:
        return "mt940"
    if suffix in {".bai2", ".bai"}:
        return "bai2"
    if suffix == ".mt942":
        return "mt942"
    return None


def _detect_xml_format(lowered: str) -> str | None:
    """Detect statement format from XML content tags."""
    if "cstmrcdttrfinitn" in lowered or "pain.001" in lowered:
        return "pain001"
    if "bktocstmrdbtcdtntfctn" in lowered or "camt.054" in lowered:
        return "camt054"
    if "bktocstmracctrpt" in lowered or "camt.052" in lowered:
        return "camt052"
    if "bktocstmrstmt" in lowered or "camt." in lowered:
        return "camt"
    return None


def _detect_by_content(text: str, lowered: str) -> str | None:
    """Detect statement format from file text contents."""
    if text.startswith("01,") or "\n01," in text:
        return "bai2"
    if ":34F:" in text and ":61:" in text:
        return "mt942"
    if "<ofx>" in lowered or "<banktranlist>" in lowered:
        return "ofx"
    if ":20:" in text and ":61:" in text:
        return "mt940"
    return None


def _detect_by_plugin(suffix: str) -> str | None:
    """Detect statement format using registered loader plugins."""
    loaders = get_registered_loaders()
    for name in loaders:
        if suffix == f".{name}" or name in suffix:
            return name
    return None


def detect_statement_format(file_name: str | Path) -> str:
    """Detect the parser format for a bank statement file."""
    path, text = _read_validated_text(file_name)
    suffix = path.suffix.lower()
    lowered = text.lower()

    if suffix == ".xml":
        xml_fmt = _detect_xml_format(lowered)
        if xml_fmt is not None:
            return xml_fmt

    detected = (
        _detect_by_suffix(suffix)
        or _detect_by_content(text, lowered)
        or _detect_by_plugin(suffix)
    )
    if detected is not None:
        return detected

    raise ValidationError(f"Unable to detect statement format: {path}")


def create_parser(
    file_name: str | Path,
    format_name: str | None = None,
) -> BankStatementParser:
    """Create a parser instance from an explicit or detected format."""
    selected = (format_name or detect_statement_format(file_name)).lower()
    parser_map: dict[str, type[BankStatementParser]] = {
        "camt": CamtParser,
        "camt052": Camt052Parser,
        "camt054": Camt054Parser,
        "pain001": Pain001Parser,
        "csv": CsvStatementParser,
        "ofx": OfxParser,
        "qfx": QfxParser,
        "mt940": Mt940Parser,
        "bai2": Bai2Parser,
    }
    # Augment with dynamic plugins
    parser_map.update(get_registered_loaders())

    if selected not in parser_map:
        raise ValidationError(f"Unsupported statement format: {selected}")
    parser_cls = parser_map[selected]
    return parser_cls(str(file_name))
