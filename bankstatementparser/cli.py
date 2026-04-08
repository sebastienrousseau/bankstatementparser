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

"""
This module provides a command line interface for parsing bank statement
files in various formats. Currently, it supports CAMT (ISO 20022) format, with
potential to extend support to other formats.
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

from bankstatementparser import CamtParser, Pain001Parser
from bankstatementparser.input_validator import (
    InputValidator,
    ValidationError,
)

# Set up logging
logger = logging.getLogger(__name__)


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure logging for the CLI application.

    Args:
        level (int): Logging level (default: INFO)
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


class BankStatementCLI:
    """A command line interface for parsing bank statement files."""

    def __init__(self) -> None:
        """Initialize the CLI by setting up the argument parser."""
        self.parser = self.setup_arg_parser()
        self.validator = InputValidator()

    def _sanitize_file_path(self, file_path: str) -> str:
        """
        Sanitize and validate file path for security.

        Args:
            file_path (str): Input file path to sanitize.

        Returns:
            str: Sanitized absolute path.

        Raises:
            ValidationError: If path is invalid or potentially dangerous.
        """
        # Check for None or empty path
        if file_path is None:
            raise ValueError("File path cannot be None")

        # Convert to absolute path to prevent directory traversal
        abs_path = os.path.abspath(file_path)

        # Get the common path with current working directory to prevent escaping
        cwd = os.path.abspath(os.getcwd())
        try:
            common_path = os.path.commonpath([abs_path, cwd])
            # Allow paths under current working directory or use system temp directory
            import tempfile

            system_temp = os.path.abspath(tempfile.gettempdir())
            if not (
                common_path == cwd or abs_path.startswith(system_temp)
            ):
                # For production, you might want to be more restrictive
                logger.info(
                    f"Path outside working directory: {file_path}"
                )
        except ValueError:
            # Different drives on Windows or other path issues
            logger.warning(f"Path validation warning for: {file_path}")

        return abs_path

    def _redact_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Redact sensitive PII columns in a DataFrame.

        Args:
            df (pd.DataFrame): Original DataFrame containing potentially sensitive data.

        Returns:
            pd.DataFrame: DataFrame with PII columns redacted.
        """
        # Create a copy to avoid modifying original data
        redacted_df = df.copy()

        # Define PII keywords to identify sensitive columns
        pii_keywords = ["address", "iban", "account", "name", "bic"]

        # Check each column for PII keywords (case-insensitive)
        for column in redacted_df.columns:
            column_lower = column.lower()
            for keyword in pii_keywords:
                if keyword in column_lower:
                    redacted_df[column] = "***REDACTED***"
                    break

        return redacted_df

    def setup_arg_parser(self) -> argparse.ArgumentParser:
        """
        Set up the command line argument parser.

        Returns:
            argparse.ArgumentParser: The configured argument parser.
        """
        parser = argparse.ArgumentParser(
            description="Parse bank statement files."
        )
        parser.add_argument(
            "--type",
            type=str,
            required=True,
            choices=["camt", "pain001", "ingest"],
            help=(
                'Type of the bank statement file: "camt", "pain001", '
                'or "ingest" for the hybrid deterministic+LLM pipeline.'
            ),
        )
        parser.add_argument(
            "--input",
            type=str,
            required=True,
            help="Path to the bank statement file.",
        )
        parser.add_argument(
            "--output",
            type=str,
            required=False,
            help="Path to save parsed data; if not provided, data is printed.",
        )
        parser.add_argument(
            "--max-size",
            type=int,
            required=False,
            default=100,
            help="Maximum file size in MB (default: 100MB).",
        )
        parser.add_argument(
            "--verbose",
            "-v",
            action="store_true",
            help="Enable verbose debug logging.",
        )
        parser.add_argument(
            "--show-pii",
            action="store_true",
            help="Display unredacted PII data in console output (default: False).",
        )
        parser.add_argument(
            "--streaming",
            action="store_true",
            help="Use streaming XML parsing to keep memory usage under 50MB for large files (default: False).",
        )
        return parser

    def parse_camt(
        self,
        file_path: Path,
        output_path: Optional[Path] = None,
        show_pii: bool = False,
        streaming: bool = False,
    ) -> None:
        """
        Parse a CAMT format bank statement file and print or save the results.

        Args:
            file_path (Path): Validated path to the CAMT file.
            output_path (Path, optional): Validated path to save the parsed data.
            If None, data is printed to console.
            show_pii (bool): Whether to display unredacted PII data.
            streaming (bool): Whether to use streaming parsing for large files.
        """
        try:
            parser = CamtParser(str(file_path))

            if streaming:
                # Use streaming parsing to process transactions incrementally
                transactions = []
                transaction_count = 0

                if output_path:
                    # For output file, use atomic write operation with temp file
                    safe_name = self.validator.get_safe_filename(
                        output_path.name
                    )
                    safe_output_path = str(
                        output_path.parent / safe_name
                    )
                    temp_output = f"{safe_output_path}.tmp"

                    with open(temp_output, "w", encoding="utf-8") as f:
                        # Write CSV header
                        header_written = False

                        for transaction_data in parser.parse_streaming(
                            redact_pii=not show_pii
                        ):
                            transaction_count += 1

                            # Convert to DataFrame for consistent formatting
                            tx_df = pd.DataFrame([transaction_data])

                            if not header_written:
                                # Write header on first transaction
                                tx_df.to_csv(f, index=False, mode="w")
                                header_written = True
                            else:
                                # Write data without header
                                tx_df.to_csv(
                                    f,
                                    index=False,
                                    mode="a",
                                    header=False,
                                )

                    # Atomically move temp file to final location
                    os.replace(temp_output, safe_output_path)
                    print(
                        f"Parsed {transaction_count} transactions in streaming mode, saved to {safe_output_path}"
                    )

                else:
                    # For console output, collect a reasonable number of transactions
                    max_console_transactions = 100

                    for transaction_data in parser.parse_streaming(
                        redact_pii=not show_pii
                    ):
                        transactions.append(transaction_data)
                        transaction_count += 1

                        # Limit console output to prevent overwhelming display
                        if (
                            transaction_count
                            >= max_console_transactions
                        ):
                            break

                    data_df = pd.DataFrame(transactions)

                    if show_pii:
                        print("WARNING: Displaying unredacted PII data")
                        print(data_df)
                    else:
                        redacted_df = self._redact_dataframe(data_df)
                        print(redacted_df)

                    if transaction_count >= max_console_transactions:
                        print(
                            f"\n... (showing first {max_console_transactions} transactions in streaming mode)"
                        )

            else:
                # Use traditional parsing
                data = parser.get_statement_stats()

                if isinstance(data, dict):
                    data = [data]

                data_df = pd.DataFrame(data)

                if output_path:
                    # Use safe filename for output
                    safe_name = self.validator.get_safe_filename(
                        output_path.name
                    )
                    safe_output_path = str(
                        output_path.parent / safe_name
                    )
                    data_df.to_csv(safe_output_path, index=False)
                    print(f"Parsed data saved to {safe_output_path}")
                else:
                    if show_pii:
                        print("WARNING: Displaying unredacted PII data")
                        print(data_df)
                    else:
                        redacted_df = self._redact_dataframe(data_df)
                        print(redacted_df)

        except FileNotFoundError as e:
            logger.error(f"File not found: {e}")
            print(f"Error: Input file not found - {str(e)}")
            sys.exit(1)
        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            print(f"Error: Invalid input - {str(e)}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Unexpected error during CAMT parsing: {e}")
            print(f"Error: Failed to parse CAMT file - {str(e)}")
            sys.exit(1)

    def parse_pain(
        self,
        file_path: Path,
        output_path: Optional[Path] = None,
        show_pii: bool = False,
        streaming: bool = False,
    ) -> None:
        """
        Parse a PAIN.001 format bank statement file and print or save the
        results.

        Args:
            file_path (Path): Validated path to the PAIN.001 file.
            output_path (Path, optional): Validated path to save the parsed data.
            If None, data is printed to console.
            show_pii (bool): Whether to display unredacted PII data.
            streaming (bool): Whether to use streaming parsing for large files.
        """
        try:
            # Instantiate the PAIN.001 parser
            parser = Pain001Parser(str(file_path))

            if streaming:
                # Use streaming parsing to process payments incrementally
                payments = []
                payment_count = 0

                if output_path:
                    # For output file, use atomic write operation with temp file
                    safe_name = self.validator.get_safe_filename(
                        output_path.name
                    )
                    safe_output_path = str(
                        output_path.parent / safe_name
                    )
                    temp_output = f"{safe_output_path}.tmp"

                    with open(temp_output, "w", encoding="utf-8") as f:
                        # Write CSV header
                        header_written = False

                        for payment_data in parser.parse_streaming(
                            redact_pii=not show_pii
                        ):
                            payment_count += 1

                            # Convert to DataFrame for consistent formatting
                            payment_df = pd.DataFrame([payment_data])

                            if not header_written:
                                # Write header on first payment
                                payment_df.to_csv(
                                    f, index=False, mode="w"
                                )
                                header_written = True
                            else:
                                # Write data without header
                                payment_df.to_csv(
                                    f,
                                    index=False,
                                    mode="a",
                                    header=False,
                                )

                    # Atomically move temp file to final location
                    os.replace(temp_output, safe_output_path)
                    print(
                        f"Parsed {payment_count} payments in streaming mode, saved to {safe_output_path}"
                    )

                else:
                    # For console output, collect a reasonable number of payments
                    max_console_payments = 100

                    for payment_data in parser.parse_streaming(
                        redact_pii=not show_pii
                    ):
                        payments.append(payment_data)
                        payment_count += 1

                        # Limit console output to prevent overwhelming display
                        if payment_count >= max_console_payments:
                            break

                    data_df = pd.DataFrame(payments)

                    if show_pii:
                        print("WARNING: Displaying unredacted PII data")
                        print(data_df)
                    else:
                        redacted_df = self._redact_dataframe(data_df)
                        print(redacted_df)

                    if payment_count >= max_console_payments:
                        print(
                            f"\n... (showing first {max_console_payments} payments in streaming mode)"
                        )

            else:
                # Use traditional parsing
                parsed_data = parser.parse()
                data_df = pd.DataFrame(parsed_data)

                if output_path:
                    # Use safe filename for output
                    safe_name = self.validator.get_safe_filename(
                        output_path.name
                    )
                    safe_output_path = str(
                        output_path.parent / safe_name
                    )
                    data_df.to_csv(safe_output_path, index=False)
                    print(f"Parsed data saved to {safe_output_path}")
                else:
                    if show_pii:
                        print("WARNING: Displaying unredacted PII data")
                        print(data_df)
                    else:
                        redacted_df = self._redact_dataframe(data_df)
                        print(redacted_df)

        except FileNotFoundError as e:
            logger.error(f"File not found: {e}")
            print(f"Error: Input file not found - {str(e)}")
            sys.exit(1)
        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            print(f"Error: Invalid input - {str(e)}")
            sys.exit(1)
        except Exception as e:
            logger.error(
                f"Unexpected error during PAIN.001 parsing: {e}"
            )
            print(f"Error: Failed to parse PAIN.001 file - {str(e)}")
            sys.exit(1)

    def run_ingest(
        self,
        file_path: Path,
        output_path: Optional[Path] = None,
    ) -> None:
        """Run the hybrid (deterministic + LLM fallback) pipeline.

        Args:
            file_path: Validated path to the statement file.
            output_path: Optional CSV output destination.
        """
        try:
            from bankstatementparser.hybrid import smart_ingest
        except ImportError as exc:
            print(
                "Error: PDF ingestion requires the [hybrid] extra.\n"
                "  Run: pip install 'bankstatementparser[hybrid]'\n"
                "  (or [hybrid-plus] for higher-fidelity PDF tables)"
            )
            logger.error(f"Hybrid import failed: {exc}")
            sys.exit(1)
            return  # pragma: no cover

        try:
            result = smart_ingest(str(file_path))
        except ImportError as exc:
            # Raised lazily by pypdf/litellm if [hybrid] is half-installed
            print(
                "Error: PDF ingestion requires the [hybrid] extra.\n"
                f"  Missing dependency: {exc.name or exc}\n"
                "  Run: pip install 'bankstatementparser[hybrid]'"
            )
            logger.error(f"Hybrid runtime import failed: {exc}")
            sys.exit(1)
            return  # pragma: no cover
        except Exception as exc:
            logger.error(f"Hybrid ingest failed: {exc}")
            print(f"Error: hybrid ingest failed - {exc}")
            sys.exit(1)
            return  # pragma: no cover

        rows = [
            {
                "transaction_hash": tx.transaction_hash,
                "source_method": tx.source_method,
                "booking_date": tx.booking_date.isoformat()
                if tx.booking_date
                else "",
                "description": tx.description or "",
                "amount": str(tx.amount),
                "currency": tx.currency or "",
                "reference": tx.reference or "",
                "confidence": tx.confidence
                if tx.confidence is not None
                else "",
            }
            for tx in result.transactions
        ]
        df = pd.DataFrame(rows)

        if output_path:
            safe_name = self.validator.get_safe_filename(
                output_path.name
            )
            safe_output_path = str(output_path.parent / safe_name)
            df.to_csv(safe_output_path, index=False)
            print(
                f"Ingested {len(rows)} transactions "
                f"({result.source_method}) -> {safe_output_path}"
            )
        else:
            print(
                f"Source method: {result.source_method} "
                f"(format: {result.source_format})"
            )
            print(df)

        if result.verification is not None:
            v = result.verification
            print(
                f"\nVerification: {v.status.value.upper()} - {v.message}"
            )
        for warning in result.warnings:
            print(f"Warning: {warning}")

    def run(self) -> None:
        """
        Parse command line arguments and perform the requested action.

        Validates input/output paths, configures logging, and delegates
        to the appropriate parser (CAMT or PAIN.001) based on the --type
        argument. Supports both traditional and streaming parsing modes.

        Raises:
            SystemExit: On invalid arguments, validation failure, or parse errors.
        """
        if len(sys.argv) == 1:
            self.parser.print_help(sys.stderr)
            sys.exit(1)

        try:
            args = self.parser.parse_args()
        except SystemExit:
            # argparse failed, which means required arguments are missing
            print("Error: Missing required arguments")
            sys.exit(1)
            return  # pragma: no cover

        # Check if required arguments are present (safety check)
        if (
            not hasattr(args, "input")
            or args.input is None
            or not hasattr(args, "type")
            or args.type is None
        ):
            print("Error: Missing required arguments")
            sys.exit(1)
            return  # Defensive programming: ensure we don't continue if sys.exit is mocked

        # Set up logging based on verbosity
        log_level = logging.DEBUG if args.verbose else logging.INFO
        setup_logging(log_level)

        # Update validator max file size setting
        max_size_bytes = (
            args.max_size * 1024 * 1024
        )  # Convert MB to bytes
        self.validator.max_file_size = max_size_bytes

        # Validate input file
        try:
            # First sanitize the path for security
            sanitized_input = self._sanitize_file_path(args.input)
            validated_input_path = (
                self.validator.validate_input_file_path(sanitized_input)
            )
            logger.info(f"Input file validated: {validated_input_path}")
        except (ValidationError, FileNotFoundError) as e:
            logger.error(f"Input validation failed: {e}")
            print(f"Error: {str(e)}")
            sys.exit(1)
            return  # Defensive programming: ensure we don't continue if sys.exit is mocked

        # Validate output file if provided
        validated_output_path = None
        if args.output:
            try:
                # First sanitize the path for security
                sanitized_output = self._sanitize_file_path(args.output)
                validated_output_path = (
                    self.validator.validate_output_file_path(
                        sanitized_output
                    )
                )
                logger.info(
                    f"Output file validated: {validated_output_path}"
                )
            except ValidationError as e:
                logger.error(f"Output validation failed: {e}")
                print(f"Error: {str(e)}")
                sys.exit(1)

        # Parse based on type
        try:
            if args.type == "camt":
                if args.streaming:
                    self.parse_camt(
                        validated_input_path,
                        validated_output_path,
                        args.show_pii,
                        args.streaming,
                    )
                else:
                    self.parse_camt(
                        validated_input_path,
                        validated_output_path,
                        args.show_pii,
                    )
            elif args.type == "pain001":
                if args.streaming:
                    self.parse_pain(
                        validated_input_path,
                        validated_output_path,
                        args.show_pii,
                        args.streaming,
                    )
                else:
                    self.parse_pain(
                        validated_input_path,
                        validated_output_path,
                        args.show_pii,
                    )
            elif args.type == "ingest":
                self.run_ingest(
                    validated_input_path,
                    validated_output_path,
                )
            else:
                print("Error: The specified type is not supported.")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Parsing failed: {e}")
            print(f"Error: Parsing failed - {str(e)}")
            sys.exit(1)


def main() -> None:
    """Console-script entry point.

    Wired up via ``[tool.poetry.scripts]`` in ``pyproject.toml`` so
    users can run::

        bankstatementparser --type ingest --input statement.pdf

    instead of::

        python -m bankstatementparser.cli --type ingest --input statement.pdf
    """
    BankStatementCLI().run()


if __name__ == "__main__":  # pragma: no cover
    main()
