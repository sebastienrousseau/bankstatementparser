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

"""Command line interface for parsing bank statement files.

Currently supports CAMT (ISO 20022) format, with potential to extend
support to other formats.
"""

import argparse
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from bankstatementparser import CamtParser, Pain001Parser, Transaction
from bankstatementparser.input_validator import (
    InputValidator,
    ValidationError,
)

# Set up logging
logger = logging.getLogger(__name__)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging for the CLI application.

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

    def _redact_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Redact sensitive PII columns in a DataFrame.

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
        """Set up the command line argument parser.

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
            choices=["camt", "pain001", "ingest", "review"],
            help=(
                'Type of operation: "camt"/"pain001" for direct '
                'parsing, "ingest" for the hybrid pipeline, or '
                '"review" to walk through a saved IngestResult JSON '
                "and resolve discrepancies."
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
        parser.add_argument(
            "--review-below",
            type=float,
            required=False,
            default=None,
            metavar="THRESHOLD",
            help=(
                "With --type review: also walk through rows whose "
                "extraction confidence is below THRESHOLD (0.0-1.0), "
                "even when statement-level verification passed."
            ),
        )
        return parser

    def parse_camt(
        self,
        file_path: Path,
        output_path: Optional[Path] = None,
        show_pii: bool = False,
        streaming: bool = False,
    ) -> None:
        """Parse a CAMT format bank statement file and print or save the results.

        Args:
            file_path (Path): Validated path to the CAMT file.
            output_path (Path, optional): Validated path to save the
                parsed data. If None, data is printed to console.
            show_pii (bool): Whether to display unredacted PII data.
            streaming (bool): Whether to use streaming parsing for large files.
        """

        def get_camt_stats(parser: Any) -> list[dict[str, Any]]:
            data = parser.get_statement_stats()
            if isinstance(data, pd.DataFrame):
                # list(DataFrame) would yield column names, not rows
                return [dict(row) for row in data.to_dict(orient="records")]
            if isinstance(data, dict):
                return [data]
            return list(data)

        self._parse_statement_file(
            file_path,
            output_path,
            show_pii,
            streaming,
            parser_factory=CamtParser,
            get_data=get_camt_stats,
            noun="transactions",
            format_label="CAMT",
        )

    def parse_pain(
        self,
        file_path: Path,
        output_path: Optional[Path] = None,
        show_pii: bool = False,
        streaming: bool = False,
    ) -> None:
        """Parse a PAIN.001 file and print or save the results.

        Args:
            file_path (Path): Validated path to the PAIN.001 file.
            output_path (Path, optional): Validated path to save the
                parsed data. If None, data is printed to console.
            show_pii (bool): Whether to display unredacted PII data.
            streaming (bool): Whether to use streaming parsing for large files.
        """
        self._parse_statement_file(
            file_path,
            output_path,
            show_pii,
            streaming,
            parser_factory=Pain001Parser,
            get_data=lambda parser: parser.parse(),
            noun="payments",
            format_label="PAIN.001",
        )

    def _parse_statement_file(
        self,
        file_path: Path,
        output_path: Optional[Path],
        show_pii: bool,
        streaming: bool,
        *,
        parser_factory: Callable[[str], Any],
        get_data: Callable[[Any], Any],
        noun: str,
        format_label: str,
    ) -> None:
        """Shared CAMT/PAIN.001 parse-and-output flow.

        Args:
            file_path: Validated path to the statement file.
            output_path: Validated path to save the parsed data, or None
                to print to console.
            show_pii: Whether to display unredacted PII data.
            streaming: Whether to use streaming parsing for large files.
            parser_factory: Builds the parser from the file path.
            get_data: Returns non-streaming records from the parser.
            noun: Record noun for user-facing messages.
            format_label: Format name for error messages.
        """
        try:
            parser = parser_factory(str(file_path))

            if streaming:
                # Process records incrementally to bound memory usage
                records = []
                record_count = 0

                if output_path:
                    # For output file, use atomic write operation with temp file
                    safe_name = self.validator.get_safe_filename(
                        output_path.name
                    )
                    safe_output_path = str(output_path.parent / safe_name)
                    temp_output = f"{safe_output_path}.tmp"

                    with open(temp_output, "w", encoding="utf-8") as f:
                        # Write CSV header
                        header_written = False

                        for record_data in parser.parse_streaming(
                            redact_pii=not show_pii
                        ):
                            record_count += 1

                            # Convert to DataFrame for consistent formatting
                            record_df = pd.DataFrame([record_data])

                            if not header_written:
                                # Write header on first record
                                record_df.to_csv(f, index=False, mode="w")
                                header_written = True
                            else:
                                # Write data without header
                                record_df.to_csv(
                                    f,
                                    index=False,
                                    mode="a",
                                    header=False,
                                )

                    # Atomically move temp file to final location
                    os.replace(temp_output, safe_output_path)
                    print(
                        f"Parsed {record_count} {noun} in streaming mode, saved to {safe_output_path}"
                    )

                else:
                    # For console output, collect a reasonable number of records
                    max_console_records = 100

                    for record_data in parser.parse_streaming(
                        redact_pii=not show_pii
                    ):
                        records.append(record_data)
                        record_count += 1

                        # Limit console output to prevent overwhelming display
                        if record_count >= max_console_records:
                            break

                    data_df = pd.DataFrame(records)

                    if show_pii:
                        print("WARNING: Displaying unredacted PII data")
                        print(data_df)
                    else:
                        redacted_df = self._redact_dataframe(data_df)
                        print(redacted_df)

                    if record_count >= max_console_records:
                        print(
                            f"\n... (showing first {max_console_records} {noun} in streaming mode)"
                        )

            else:
                # Use traditional parsing
                data_df = pd.DataFrame(get_data(parser))

                if output_path:
                    # Use safe filename for output
                    safe_name = self.validator.get_safe_filename(
                        output_path.name
                    )
                    safe_output_path = str(output_path.parent / safe_name)
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
            print(f"Error: Input file not found - {e!s}")
            sys.exit(1)
        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            print(f"Error: Invalid input - {e!s}")
            sys.exit(1)
        except Exception as e:
            logger.error(
                f"Unexpected error during {format_label} parsing: {e}"
            )
            print(f"Error: Failed to parse {format_label} file - {e!s}")
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
                "source_page": tx.source_page
                if tx.source_page is not None
                else "",
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
            safe_name = self.validator.get_safe_filename(output_path.name)
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
            print(f"\nVerification: {v.status.value.upper()} - {v.message}")
        for warning in result.warnings:
            print(f"Warning: {warning}")

    def run_review(
        self,
        file_path: Path,
        output_path: Optional[Path] = None,
        review_below: Optional[float] = None,
    ) -> None:
        """Walk through a saved IngestResult JSON and resolve discrepancies.

        Reads the file produced by ``--type ingest --output ...``
        (when that file is JSON) or any other source that emits an
        :class:`~bankstatementparser.hybrid.IngestResult` via its
        ``to_json()`` method. When the statement-level status is
        :class:`VerificationStatus.DISCREPANCY` or
        :class:`VerificationStatus.FAILED`, every transaction is
        reviewed. Independently, ``review_below`` routes individual
        low-confidence rows into the same flow even when the
        statement verified cleanly. The operator is prompted with a
        single-character action menu:

        * ``a`` accept the row as-is
        * ``e`` edit the description and amount
        * ``s`` skip (leave unresolved)
        * ``d`` delete the row from the result
        * ``q`` quit early without writing further changes

        Every action is recorded in the ``audit_trail`` field of
        the saved result, so the audit history is preserved across
        review sessions. After the walk, the Golden Rule is re-run
        on the kept rows so edits and deletions are reflected in
        the saved verification verdict.

        Args:
            file_path: Validated path to the IngestResult JSON.
            output_path: Optional destination; defaults to
                rewriting ``file_path`` in place.
            review_below: Optional confidence threshold (0.0-1.0).
                Rows with ``confidence`` below this value are
                reviewed even when verification passed.

        The CLI is non-curses (plain stdin/stdout) so it works on
        any terminal and is straightforward to mock in CI.
        """
        try:
            from bankstatementparser.hybrid import (
                IngestResult,
                VerificationStatus,
                verify_transactions,
            )
        except ImportError as exc:
            print(
                "Error: review mode requires the [hybrid] extra.\n"
                "  Run: pip install 'bankstatementparser[hybrid]'"
            )
            logger.error(f"Hybrid import failed: {exc}")
            sys.exit(1)
            return  # pragma: no cover

        try:
            payload = file_path.read_text(encoding="utf-8")
            result = IngestResult.from_json(payload)
        except Exception as exc:
            logger.error(f"Failed to load IngestResult: {exc}")
            print(f"Error: cannot load IngestResult JSON - {exc}")
            sys.exit(1)
            return  # pragma: no cover

        v = result.verification
        review_all = v is not None and v.status is not (
            VerificationStatus.VERIFIED
        )
        low_confidence = (
            {
                index
                for index, tx in enumerate(result.transactions)
                if tx.confidence is not None and tx.confidence < review_below
            }
            if review_below is not None
            else set()
        )

        if not review_all and not low_confidence:
            status_label = v.status.value.upper() if v else "absent"
            if review_below is not None:
                print(
                    f"Verification status is {status_label} and no rows "
                    f"are below confidence {review_below:.2f} — nothing "
                    "to review."
                )
            else:
                print(
                    f"Verification status is {status_label}"
                    " — nothing to review."
                )
            return

        if v is not None:
            print(f"Verification: {v.status.value.upper()} - {v.message}")
        if not review_all:
            print(
                f"Reviewing {len(low_confidence)} rows below "
                f"confidence {review_below:.2f}."
            )
        print(f"Loaded {len(result.transactions)} transactions.")
        print()

        kept: list[Transaction] = []
        audit: list[dict[str, object]] = list(result.audit_trail)

        for index, tx in enumerate(result.transactions):
            if not review_all and index not in low_confidence:
                kept.append(tx)
                continue
            self._render_review_row(index, len(result.transactions), tx)
            action = self._prompt_review_action()

            if action == "q":
                # Append everything from this row onward unchanged
                # and stop reviewing further rows.
                kept.extend(result.transactions[index:])
                audit.append(
                    {
                        "row_index": index,
                        "action": "quit",
                    }
                )
                print("Review session quit by operator.")
                break
            elif action == "a":
                kept.append(tx)
                audit.append({"row_index": index, "action": "accept"})
            elif action == "s":
                kept.append(tx)
                audit.append({"row_index": index, "action": "skip"})
            elif action == "d":
                audit.append(
                    {
                        "row_index": index,
                        "action": "delete",
                        "deleted_hash": tx.transaction_hash,
                    }
                )
            else:
                # action is guaranteed to be "e" by
                # _prompt_review_action's whitelist; this branch is
                # the only remaining option.
                edited = self._edit_review_row(tx)
                kept.append(edited)
                audit.append(
                    {
                        "row_index": index,
                        "action": "edit",
                        "before_hash": tx.transaction_hash,
                        "after_hash": edited.transaction_hash,
                    }
                )

        # Reconstruct the result with the kept transactions, the
        # appended audit trail, and a verification verdict re-run
        # against the kept rows so edits and deletions are reflected
        # in the saved status.
        from dataclasses import replace

        new_verification = result.verification
        if result.verification is not None:
            new_verification = verify_transactions(
                kept,
                opening_balance=result.verification.opening_balance,
                closing_balance=result.verification.closing_balance,
            )
            audit.append(
                {
                    "action": "reverify",
                    "status_before": result.verification.status.value,
                    "status_after": new_verification.status.value,
                }
            )

        updated = replace(
            result,
            transactions=tuple(kept),
            verification=new_verification,
            audit_trail=tuple(audit),
        )

        output_target = output_path or file_path
        safe_name = self.validator.get_safe_filename(output_target.name)
        safe_output = str(output_target.parent / safe_name)
        Path(safe_output).write_text(updated.to_json(), encoding="utf-8")
        print(f"\nReview complete. Wrote {len(kept)} rows -> {safe_output}")
        print(f"Audit trail entries: {len(audit)}")
        if new_verification is not None:
            print(
                f"Re-verified: {new_verification.status.value.upper()} - "
                f"{new_verification.message}"
            )

    def _render_review_row(
        self,
        index: int,
        total: int,
        tx: Transaction,
    ) -> None:
        """Print a single transaction in human-readable form."""
        date = (
            tx.booking_date.isoformat()
            if tx.booking_date is not None
            else "????-??-??"
        )
        desc = tx.description or "(no description)"
        amount = tx.amount
        confidence = tx.confidence
        raw = tx.raw_source_text
        bbox = tx.source_bbox

        print(f"--- Row {index + 1} of {total} ---")
        print(f"  date:        {date}")
        print(f"  description: {desc}")
        print(f"  amount:      {amount}")
        if confidence is not None:
            print(f"  confidence:  {confidence:.2f}")
        if raw:
            print(f"  source text: {raw[:160]}")
        if tx.source_page is not None:
            print(f"  source page: {tx.source_page}")
        if bbox is not None:
            print(
                "  source bbox: "
                f"({bbox.x0:.3f}, {bbox.y0:.3f}) -> "
                f"({bbox.x1:.3f}, {bbox.y1:.3f}) "
                f"page {bbox.page_index}"
            )

    def _prompt_review_action(self) -> str:
        """Prompt the operator for an action character.

        Loops until a valid character is entered. Reads from the
        process stdin so tests can replace ``sys.stdin`` with an
        ``io.StringIO`` to drive deterministic flows.
        """
        valid = {"a", "e", "s", "d", "q"}
        while True:
            try:
                raw_input = input(
                    "  [a]ccept / [e]dit / [s]kip / [d]elete / [q]uit > "
                )
            except EOFError:
                # No more input — treat as quit so the test runner
                # gets a clean exit instead of hanging.
                return "q"
            value = raw_input.strip().lower()[:1]
            if value in valid:
                return value
            print("  Please enter one of: a, e, s, d, q")

    def _edit_review_row(self, tx: Transaction) -> Transaction:
        """Prompt the operator for new description and amount.

        Returns a fresh ``Transaction`` with the edits applied. The
        ``transaction_hash`` is automatically recomputed by the
        Pydantic computed field.
        """
        from decimal import Decimal, InvalidOperation

        from bankstatementparser.transaction_models import (
            normalize_description,
        )

        current_desc = tx.description or ""
        current_amount = tx.amount
        try:
            new_desc = (
                input(f"  new description [{current_desc}]: ") or current_desc
            )
            new_amount_raw = input(
                f"  new amount      [{current_amount}]: "
            ) or str(current_amount)
            new_amount = Decimal(new_amount_raw)
        except (EOFError, InvalidOperation):
            print("  edit aborted; keeping original row")
            return tx

        return Transaction(
            account_id=tx.account_id,
            currency=tx.currency,
            amount=new_amount,
            booking_date=tx.booking_date,
            value_date=tx.value_date,
            description=new_desc,
            normalized_description=normalize_description(new_desc),
            reference=tx.reference,
            transaction_id=tx.transaction_id,
            counterparty=tx.counterparty,
            source=tx.source,
            source_index=tx.source_index,
            source_method=tx.source_method,
            confidence=tx.confidence,
            category=tx.category,
            raw_source_text=tx.raw_source_text,
            source_bbox=tx.source_bbox,
        )

    def run(self) -> None:
        """Parse command line arguments and perform the requested action.

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
        max_size_bytes = args.max_size * 1024 * 1024  # Convert MB to bytes
        self.validator.max_file_size = max_size_bytes

        # Validate input file
        try:
            validated_input_path = self.validator.validate_input_file_path(
                args.input
            )
            logger.info(f"Input file validated: {validated_input_path}")
        except (ValidationError, FileNotFoundError) as e:
            logger.error(f"Input validation failed: {e}")
            print(f"Error: {e!s}")
            sys.exit(1)
            return  # Defensive programming: ensure we don't continue if sys.exit is mocked

        # Validate output file if provided
        validated_output_path = None
        if args.output:
            try:
                validated_output_path = (
                    self.validator.validate_output_file_path(args.output)
                )
                logger.info(f"Output file validated: {validated_output_path}")
            except ValidationError as e:
                logger.error(f"Output validation failed: {e}")
                print(f"Error: {e!s}")
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
            elif args.type == "review":
                if args.review_below is not None and not (
                    0.0 <= args.review_below <= 1.0
                ):
                    print("Error: --review-below must be between 0.0 and 1.0")
                    sys.exit(1)
                self.run_review(
                    validated_input_path,
                    validated_output_path,
                    review_below=args.review_below,
                )
            else:
                print("Error: The specified type is not supported.")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Parsing failed: {e}")
            print(f"Error: Parsing failed - {e!s}")
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
