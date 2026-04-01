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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
`bankstatementparser` package provides useful tools for finance and
treasury specialists.

This package includes modules for parsing bank statements in various
formats, as well as other utilities commonly used in finance and treasury
operations.
"""

from .additional_parsers import (
    CsvStatementParser,
    Mt940Parser,
    OfxParser,
    QfxParser,
    create_parser,
    detect_statement_format,
)
from .base_parser import BankStatementParser
from .camt_parser import CamtParser
from .exceptions import (
    BankStatementParserError,
    ExportError,
    Pain001ParseError,
    ParserError,
)
from .input_validator import InputValidator, ValidationError
from .pain001_parser import Pain001Parser
from .parallel import FileResult, parse_files_parallel
from .transaction_deduplicator import (
    DeduplicationResult,
    Deduplicator,
    ExactDuplicateGroup,
    MatchGroup,
)
from .transaction_models import Transaction
from .zip_security import (
    ZipSecurityError,
    ZipXMLSource,
    iter_secure_xml_entries,
)

__all__ = [
    "BankStatementParser",
    "BankStatementParserError",
    "CamtParser",
    "CsvStatementParser",
    "ExportError",
    "OfxParser",
    "QfxParser",
    "Mt940Parser",
    "detect_statement_format",
    "create_parser",
    "Pain001Parser",
    "Pain001ParseError",
    "ParserError",
    "Transaction",
    "Deduplicator",
    "DeduplicationResult",
    "ExactDuplicateGroup",
    "MatchGroup",
    "FileResult",
    "parse_files_parallel",
    "InputValidator",
    "ValidationError",
    "ZipSecurityError",
    "ZipXMLSource",
    "iter_secure_xml_entries",
]
