# Copyright (C) 2023 Sebastien Rousseau.
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

"""Repository-wide exception hierarchy."""

from __future__ import annotations

from defusedxml.ElementTree import ParseError


class BankStatementParserError(Exception):
    """Base exception for parser-specific failures."""


class ExportError(OSError, BankStatementParserError):
    """Raised when an export operation cannot complete safely."""


class ParserError(BankStatementParserError):
    """Raised when parser logic cannot produce a valid result."""


class Pain001ParseError(ParseError, ParserError):  # type: ignore[misc]
    """Raised when PAIN.001 parsing fails after XML loading succeeds."""
