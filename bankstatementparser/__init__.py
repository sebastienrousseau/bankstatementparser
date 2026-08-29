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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tools for finance and treasury specialists.

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
from .transaction_models import BoundingBox, Transaction
from .zip_security import (
    ZipSecurityError,
    ZipXMLSource,
    iter_secure_xml_entries,
)

#: The package version, restated here as every other package in the
#: suite does. It is a literal rather than an importlib.metadata lookup
#: so the conformance gate can compare it statically against
#: pyproject.toml -- that comparison is the thing that catches drift, and
#: a runtime lookup would make the two trivially equal and check nothing.
__version__ = "0.0.18"

__all__ = [
    "BankStatementParser",
    "BankStatementParserError",
    "BoundingBox",
    "CamtParser",
    "CsvStatementParser",
    "DeduplicationResult",
    "Deduplicator",
    "ExactDuplicateGroup",
    "ExportError",
    "FileResult",
    "InputValidator",
    "MatchGroup",
    "Mt940Parser",
    "OfxParser",
    "Pain001ParseError",
    "Pain001Parser",
    "ParserError",
    "QfxParser",
    "Transaction",
    "ValidationError",
    "ZipSecurityError",
    "ZipXMLSource",
    "__version__",
    "create_parser",
    "detect_statement_format",
    "iter_secure_xml_entries",
    "parse_files_parallel",
]
