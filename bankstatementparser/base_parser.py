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

"""
base_parser.py

Abstract base class for bank statement parsers providing a standardized
interface for parsing different bank statement formats.
"""

import importlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Union

import pandas as pd

from .exceptions import ExportError
from .record_types import SummaryRecord

if TYPE_CHECKING:
    import polars as pl


class BankStatementParser(ABC):
    """
    Abstract base class for bank statement parsers.

    This class defines a standardized interface that all bank statement
    parsers should implement, ensuring consistency across different
    statement formats (CAMT, PAIN001, etc.).

    Attributes:
        file_name (str): Path to the bank statement file being parsed.
    """

    def __init__(self, file_name: Union[str, Path]) -> None:
        """
        Initialize the parser with a file path.

        Args:
            file_name (Union[str, Path]): Path to the bank statement file.
        """
        self.file_name = str(file_name)

    @abstractmethod
    def parse(self) -> pd.DataFrame:
        """
        Parse the bank statement file and return structured data.

        This method should parse the bank statement file and return
        a pandas DataFrame containing the parsed transaction data
        in a standardized format.

        Returns:
            pd.DataFrame: Parsed transaction data with standardized columns.

        Raises:
            FileNotFoundError: If the file cannot be found.
            ValidationError: If the file format is invalid.
            Exception: For other parsing errors.
        """
        pass

    @abstractmethod
    def get_summary(self) -> SummaryRecord:
        """
        Get a summary of the parsed bank statement data.

        This method should return key statistics and metadata about
        the bank statement, such as account information, balance data,
        transaction counts, and totals.

        Returns:
            Dict[str, Any]: Summary information including:
                - account_id: Account identifier
                - statement_date: Statement date/period
                - transaction_count: Number of transactions
                - total_amount: Sum of all transactions
                - opening_balance: Opening balance (if available)
                - closing_balance: Closing balance (if available)
                - currency: Statement currency
        """
        pass

    def export_csv(self, output_path: Union[str, Path]) -> None:
        """
        Export parsed data to a CSV file.

        Args:
            output_path (Union[str, Path]): Path where CSV file should be saved.

        Raises:
            IOError: If file cannot be written.
        """
        temp_path = Path(f"{output_path}.tmp")
        try:
            df = self.parse()
            df.to_csv(temp_path, index=False)

            # Atomic rename to prevent corruption
            temp_path.replace(output_path)
        except Exception as exc:
            # Clean up temp file if it exists
            if temp_path.exists():
                temp_path.unlink()
            raise ExportError(
                f"Failed to export CSV: {exc}"
            ) from exc

    def export_json(self, output_path: Union[str, Path]) -> None:
        """
        Export parsed data to a JSON file.

        Args:
            output_path (Union[str, Path]): Path where JSON file should be saved.

        Raises:
            IOError: If file cannot be written.
        """
        temp_path = Path(f"{output_path}.tmp")
        try:
            df = self.parse()

            # Create structured JSON with summary and transactions
            data = {
                "summary": self.get_summary(),
                "transactions": df.to_dict("records"),
            }

            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)

            # Atomic rename to prevent corruption
            temp_path.replace(output_path)
        except Exception as exc:
            # Clean up temp file if it exists
            if temp_path.exists():
                temp_path.unlink()
            raise ExportError(
                f"Failed to export JSON: {exc}"
            ) from exc

    def to_polars(self) -> "pl.DataFrame":
        """
        Convert parsed transaction data to a Polars DataFrame.

        Returns:
            Any: ``polars.DataFrame`` for the parsed data.

        Raises:
            ImportError: If the optional ``polars`` dependency is not installed.
        """
        try:
            polars = importlib.import_module("polars")
        except ImportError as exc:
            raise ImportError(
                "Run 'pip install bankstatementparser[polars]' to use this feature."
            ) from exc

        return polars.from_pandas(self.parse())

    def to_polars_lazy(self) -> "pl.LazyFrame":
        """
        Convert parsed transaction data to a Polars LazyFrame.

        Returns:
            Any: ``polars.LazyFrame`` for the parsed data.
        """
        return self.to_polars().lazy()

    def __repr__(self) -> str:
        """
        Return a string representation of the parser.

        Returns:
            str: String representation including parser type and file name.
        """
        return f"{self.__class__.__name__}(file='{self.file_name}')"

    def __str__(self) -> str:
        """
        Return a human-readable string representation.

        Returns:
            str: Human-readable representation with summary information.
        """
        try:
            summary = self.get_summary()
            return (
                f"{self.__class__.__name__}: "
                f"Account {summary.get('account_id', 'Unknown')}, "
                f"{summary.get('transaction_count', 0)} transactions"
            )
        except Exception:
            return f"{self.__class__.__name__}(file='{self.file_name}')"
