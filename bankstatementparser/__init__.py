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
from .analytics import (
    AnalyticsReport,
    AnomalyFinding,
    CashFlowMetrics,
    RecurringCadence,
    RecurringPattern,
    analyze_statement_transactions,
    compute_cash_flow_summary,
    detect_anomalies_and_nsf,
    detect_recurring_transactions,
)
from .base_parser import BankStatementParser
from .camt_parser import CamtParser
from .exceptions import (
    BankStatementParserError,
    ExportError,
    Pain001ParseError,
    ParserError,
)
from .export.parquet import export_parquet
from .field86_parser import Field86Structure, parse_field_86
from .forensics import (
    ForensicFinding,
    ForensicsReport,
    ForensicVerdict,
    inspect_pdf_forensics,
)
from .input_validator import InputValidator, ValidationError
from .pain001_parser import Pain001Parser
from .parallel import FileResult, parse_files_parallel
from .plugins import (
    discover_loaders,
    discover_writers,
    register_loader,
    register_writer,
)
from .reconciliation import (
    ReconciliationMatch,
    ReconciliationReport,
    ReconciliationStatus,
    reconcile_payments_and_statements,
)
from .transaction_deduplicator import (
    DeduplicationResult,
    Deduplicator,
    ExactDuplicateGroup,
    MatchGroup,
)
from .transaction_models import BoundingBox, Transaction
from .zip_security import (
    ZipSecurityError,
    ZipStatementSource,
    ZipXMLSource,
    iter_secure_statement_entries,
    iter_secure_xml_entries,
)

#: The package version, restated here as every other package in the
#: suite does. It is a literal rather than an importlib.metadata lookup
#: so the conformance gate can compare it statically against
#: pyproject.toml -- that comparison is the thing that catches drift, and
#: a runtime lookup would make the two trivially equal and check nothing.
__version__ = "0.0.19"

__all__ = [
    "AnalyticsReport",
    "AnomalyFinding",
    "BankStatementParser",
    "BankStatementParserError",
    "BoundingBox",
    "CamtParser",
    "CashFlowMetrics",
    "CsvStatementParser",
    "DeduplicationResult",
    "Deduplicator",
    "ExactDuplicateGroup",
    "ExportError",
    "Field86Structure",
    "FileResult",
    "ForensicFinding",
    "ForensicVerdict",
    "ForensicsReport",
    "InputValidator",
    "MatchGroup",
    "Mt940Parser",
    "OfxParser",
    "Pain001ParseError",
    "Pain001Parser",
    "ParserError",
    "QfxParser",
    "ReconciliationMatch",
    "ReconciliationReport",
    "ReconciliationStatus",
    "RecurringCadence",
    "RecurringPattern",
    "Transaction",
    "ValidationError",
    "ZipSecurityError",
    "ZipStatementSource",
    "ZipXMLSource",
    "__version__",
    "analyze_statement_transactions",
    "compute_cash_flow_summary",
    "create_parser",
    "detect_anomalies_and_nsf",
    "detect_recurring_transactions",
    "detect_statement_format",
    "discover_loaders",
    "discover_writers",
    "export_parquet",
    "inspect_pdf_forensics",
    "iter_secure_statement_entries",
    "iter_secure_xml_entries",
    "parse_field_86",
    "parse_files_parallel",
    "reconcile_payments_and_statements",
    "register_loader",
    "register_writer",
]
